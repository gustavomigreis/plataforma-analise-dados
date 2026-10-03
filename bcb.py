"""
Integração com indicadores macroeconômicos do Banco Central do Brasil:
Selic, inflação (IPCA), câmbio (USD/BRL) e dívida pública (% do PIB).

Duas fontes, com fallback automático:
1. API REST SGS (api.bcb.gov.br) — fonte principal, documentação em
   https://dadosabertos.bcb.gov.br/dataset/
2. Webservice SOAP legado do SGS (www3.bcb.gov.br/wssgs) — usado como
   fallback automático quando a API REST falha.

MOTIVO DO FALLBACK: a partir de 03/10/2026, api.bcb.gov.br passou a
retornar NXDOMAIN (falha de resolução DNS) de forma consistente, inclusive
testado contra múltiplos resolvedores DNS públicos (Cloudflare, Google,
Quad9) — ou seja, não é um problema do ambiente onde a plataforma roda,
é uma instabilidade/queda da própria API REST do BCB, documentada de forma
independente por outros projetos open-source na mesma data. O webservice
SOAP legado (tecnologia mais antiga, infraestrutura separada) continuava
no ar normalmente quando isso foi investigado.
"""
import html
import re
from datetime import datetime, date

from net_utils import request_com_retry

SGS_BASE = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs'
SOAP_URL = 'https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS'

# Catálogo de indicadores macro disponíveis (código de série SGS do BCB)
INDICADORES = {
    'selic_meta': {
        'codigo': 432,
        'nome': 'Taxa Selic (Meta)',
        'unidade': '% a.a.',
        'frequencia': 'eventos do Copom',
    },
    'ipca_mensal': {
        'codigo': 433,
        'nome': 'IPCA (Variação Mensal)',
        'unidade': '%',
        'frequencia': 'mensal',
    },
    'ipca_12_meses': {
        'codigo': 13522,
        'nome': 'IPCA (Acumulado 12 Meses)',
        'unidade': '%',
        'frequencia': 'mensal',
    },
    'cambio_usd': {
        'codigo': 1,
        'nome': 'Câmbio USD/BRL (PTAX Venda)',
        'unidade': 'R$',
        'frequencia': 'diária',
    },
    'divida_pib': {
        'codigo': 13762,
        'nome': 'Dívida Bruta do Governo Geral (% do PIB)',
        'unidade': '% do PIB',
        'frequencia': 'mensal',
    },
}

_SOAP_ENVELOPE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:pub="http://publico.ws.casosdeuso.sgs.pec.bcb.gov.br">'
    '<soapenv:Body><pub:getValoresSeriesXML>'
    '<codigosSeries><item>{codigo}</item></codigosSeries>'
    '<dataInicio>{ini}</dataInicio><dataFim>{fim}</dataFim>'
    '</pub:getValoresSeriesXML></soapenv:Body></soapenv:Envelope>'
)
_SOAP_ITEM_RE = re.compile(r'<DATA>\s*([^<]*?)\s*</DATA>\s*<VALOR>\s*([^<]*?)\s*</VALOR>', re.S)
_SOAP_FAULT_RE = re.compile(r'<faultstring>(.*?)</faultstring>', re.S)


def _parse_data_br(data_str):
    """Converte 'DD/MM/AAAA' em 'AAAA-MM-DD' para ordenação/exibição consistente."""
    try:
        return datetime.strptime(data_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return data_str


def _buscar_via_rest(codigo, quantidade, data_inicial, data_final):
    """Tenta a API REST (fonte principal). Deixa a exceção propagar se falhar
    (quem chama decide se cai para o fallback SOAP)."""
    if data_inicial and data_final:
        url = f'{SGS_BASE}.{codigo}/dados'
        params = {'formato': 'json', 'dataInicial': data_inicial, 'dataFinal': data_final}
    else:
        url = f'{SGS_BASE}.{codigo}/dados/ultimos/{quantidade}'
        params = {'formato': 'json'}

    resp = request_com_retry('get', url, params=params, timeout=15, tentativas=2)
    resp.raise_for_status()
    dados_brutos = resp.json()

    resultado = []
    for item in dados_brutos:
        try:
            valor = float(item['valor'].replace(',', '.')) if isinstance(item['valor'], str) else float(item['valor'])
        except (ValueError, KeyError, AttributeError):
            valor = None

        resultado.append({
            'data': item.get('data'),
            'periodo': _parse_data_br(item.get('data')),
            'valor': valor,
        })

    return resultado


def _data_str_para_date(texto):
    """Converte 'DD/MM/AAAA' ou 'MM/AAAA' (séries mensais) em um objeto date."""
    partes = [int(p) for p in texto.split('/')]
    if len(partes) == 3:
        return date(partes[2], partes[1], partes[0])
    if len(partes) == 2:
        return date(partes[1], partes[0], 1)
    raise ValueError(f'Formato de data inesperado: {texto}')


def _buscar_via_soap(codigo, quantidade, data_inicial, data_final):
    """
    Fallback: consulta o webservice SOAP legado do SGS (www3.bcb.gov.br/wssgs).
    Usado quando a API REST está fora do ar.
    """
    if data_inicial and data_final:
        dt_ini = datetime.strptime(data_inicial, '%d/%m/%Y').date()
        dt_fim = datetime.strptime(data_final, '%d/%m/%Y').date()
    else:
        # Sem intervalo explícito: busca uma janela ampla (5 anos) e depois
        # corta para os últimos N registros, já que o SOAP não tem um
        # equivalente direto a "/ultimos/N".
        dt_fim = date.today()
        dt_ini = date(dt_fim.year - 5, dt_fim.month, dt_fim.day)

    corpo = _SOAP_ENVELOPE.format(
        codigo=int(codigo),
        ini=dt_ini.strftime('%d/%m/%Y'),
        fim=dt_fim.strftime('%d/%m/%Y'),
    )
    resp = request_com_retry(
        'post', SOAP_URL, data=corpo.encode('utf-8'), timeout=60, tentativas=2,
        headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': ''}
    )

    falha = _SOAP_FAULT_RE.search(resp.text or '')
    if falha:
        raise RuntimeError(f'SOAP do BCB recusou a série {codigo}: {falha.group(1).strip()[:200]}')
    resp.raise_for_status()

    pares = _SOAP_ITEM_RE.findall(html.unescape(resp.text or ''))
    resultado = []
    for data_bruta, valor_bruto in pares:
        try:
            dt = _data_str_para_date(data_bruta)
            valor = float(valor_bruto.replace(',', '.'))
        except ValueError:
            continue
        resultado.append({
            'data': dt.strftime('%d/%m/%Y'),
            'periodo': dt.strftime('%Y-%m-%d'),
            'valor': valor,
        })

    resultado.sort(key=lambda r: r['periodo'])

    if not data_inicial and not data_final:
        resultado = resultado[-quantidade:]

    return resultado


def buscar_serie(chave_indicador, quantidade=24, data_inicial=None, data_final=None):
    """
    Busca uma série histórica de um indicador macro do BCB. Tenta a API REST
    primeiro; se falhar (ex: indisponibilidade/DNS), usa automaticamente o
    fallback via webservice SOAP legado.

    chave_indicador: uma das chaves em INDICADORES (ex: 'selic_meta')
    quantidade: número de registros mais recentes a buscar (ignorado se
                data_inicial/data_final forem informados)
    data_inicial, data_final: strings 'DD/MM/AAAA' (opcional, para um intervalo específico)

    Retorna uma lista de dicts: {data, periodo (AAAA-MM-DD), valor, indicador, unidade}
    """
    if chave_indicador not in INDICADORES:
        raise ValueError(
            f'Indicador inválido: {chave_indicador}. '
            f'Opções: {", ".join(INDICADORES.keys())}'
        )

    info = INDICADORES[chave_indicador]
    codigo = info['codigo']

    try:
        pares = _buscar_via_rest(codigo, quantidade, data_inicial, data_final)
    except Exception:
        pares = _buscar_via_soap(codigo, quantidade, data_inicial, data_final)

    return [
        {**par, 'indicador': info['nome'], 'unidade': info['unidade']}
        for par in pares
    ]


def buscar_ultimo_valor(chave_indicador):
    """Retorna apenas o valor mais recente de um indicador (útil para painéis-resumo)."""
    serie = buscar_serie(chave_indicador, quantidade=1)
    return serie[-1] if serie else None
