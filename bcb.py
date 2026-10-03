"""
Integração com a API SGS (Sistema Gerenciador de Séries Temporais) do
Banco Central do Brasil, para indicadores macroeconômicos nacionais:
Selic, inflação (IPCA), câmbio (USD/BRL) e dívida pública (% do PIB).

Documentação: https://dadosabertos.bcb.gov.br/dataset/
Sem necessidade de API key. Formato de resposta padrão: lista de objetos
{"data": "DD/MM/AAAA", "valor": "<string decimal>"}.
"""
import requests
from datetime import datetime

SGS_BASE = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs'

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


def _parse_data_br(data_str):
    """Converte 'DD/MM/AAAA' em 'AAAA-MM-DD' para ordenação/exibição consistente."""
    try:
        return datetime.strptime(data_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return data_str


def buscar_serie(chave_indicador, quantidade=24, data_inicial=None, data_final=None):
    """
    Busca uma série histórica do BCB/SGS.

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

    if data_inicial and data_final:
        url = f'{SGS_BASE}.{codigo}/dados'
        params = {'formato': 'json', 'dataInicial': data_inicial, 'dataFinal': data_final}
    else:
        url = f'{SGS_BASE}.{codigo}/dados/ultimos/{quantidade}'
        params = {'formato': 'json'}

    resp = requests.get(url, params=params, timeout=30)
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
            'indicador': info['nome'],
            'unidade': info['unidade'],
        })

    return resultado


def buscar_ultimo_valor(chave_indicador):
    """Retorna apenas o valor mais recente de um indicador (útil para painéis-resumo)."""
    serie = buscar_serie(chave_indicador, quantidade=1)
    return serie[-1] if serie else None
