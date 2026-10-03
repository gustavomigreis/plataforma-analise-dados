"""
Integração com a API pública do Comex Stat (MDIC/Secex) para dados de
comércio exterior (exportações e importações) por município.

Documentação: https://api-comexstat.mdic.gov.br/docs
Sem necessidade de API key.

IMPORTANTE: o filtro por município nesta API é pelo "município de domicílio
fiscal" do exportador/importador (endereço do CNPJ), não necessariamente o
local onde a mercadoria foi produzida ou embarcada. Isso é uma limitação da
fonte oficial, não desta implementação — deve ficar claro para quem for
interpretar os dados.
"""
from net_utils import request_com_retry

COMEX_BASE = 'https://api-comexstat.mdic.gov.br'

# ATENÇÃO: a API do Comex Stat usa sua PRÓPRIA tabela de códigos de UF,
# diferente do código IBGE. Confirmado contra o endpoint oficial de filtros
# (GET /general/filters/state): no Comex Stat, 42 = Paraná e 44 = Santa
# Catarina (no IBGE, SC é 42). Um bug anterior usava o código do IBGE (42)
# aqui e retornava, silenciosamente, dados do Paraná em vez de SC.
UF_SC = 44

FLUXOS = {
    'exportacao': 'export',
    'importacao': 'import',
}


def buscar_comercio_exterior(fluxo, ano_inicio, ano_fim, codigo_municipio=None, uf=UF_SC):
    """
    Consulta a API do Comex Stat para exportações ou importações.

    fluxo: 'exportacao' ou 'importacao'
    ano_inicio, ano_fim: strings 'YYYY' (ex: '2023', '2024')
    codigo_municipio: código IBGE do município (opcional - se None, traz todos os municípios da UF)
    uf: código da UF (padrão: Santa Catarina)

    Retorna uma lista de dicts: município, valor FOB (US$), peso líquido (kg), ano
    """
    if fluxo not in FLUXOS:
        raise ValueError(f'Fluxo inválido: {fluxo}. Use "exportacao" ou "importacao"')

    filtros = [{'filter': 'state', 'values': [str(uf)]}]
    if codigo_municipio:
        filtros.append({'filter': 'city', 'values': [str(codigo_municipio)]})

    payload = {
        'flow': FLUXOS[fluxo],
        'monthDetail': False,
        'period': {'from': f'{ano_inicio}-01', 'to': f'{ano_fim}-12'},
        'filters': filtros,
        'details': ['city'],
        'metrics': ['metricFOB', 'metricKG'],
    }

    resp = request_com_retry('post', f'{COMEX_BASE}/cities', json=payload, timeout=30)
    resp.raise_for_status()
    dados_brutos = resp.json()

    # A API retorna um objeto com os dados em 'data' -> 'list'. Confirmado em
    # produção (teste real com SC/exportações, 474 registros): o nome do
    # município vem no campo 'noMunMinsgUf', no formato "Nome do Município - UF"
    # (ex: "Palhoça - SC"), e não em 'city'/'coCity' como a documentação sugeria.
    lista = dados_brutos.get('data', {}).get('list', [])

    resultado = []
    for item in lista:
        nome_mun_uf = item.get('noMunMinsgUf')
        if nome_mun_uf:
            municipio, _, sigla_uf = nome_mun_uf.rpartition(' - ')
        else:
            municipio, sigla_uf = 'Desconhecido', None

        # Checagem defensiva: garante que o registro é mesmo de SC, já que um
        # código de UF incorreto no filtro causaria silenciosamente dados de
        # outro estado (como aconteceu antes com o código do IBGE em vez do
        # código próprio do Comex Stat). Se a UF vier e não for SC, descarta.
        if sigla_uf and uf == UF_SC and sigla_uf != 'SC':
            continue

        resultado.append({
            'municipio': municipio,
            'valor_fob_usd': item.get('metricFOB'),
            'peso_liquido_kg': item.get('metricKG'),
            'fluxo': fluxo,
            'periodo': f'{ano_inicio}-{ano_fim}',
        })

    # Ordena por valor FOB decrescente — não garantido pela API em si, mas é
    # a ordem mais útil para quem consulta (maiores exportadores/importadores
    # primeiro) e o que a interface assume ao mostrar só os top N num gráfico.
    resultado.sort(key=lambda r: r['valor_fob_usd'] or 0, reverse=True)

    return resultado


def listar_municipios_disponiveis_sc():
    """
    Lista os municípios de SC com dados disponíveis no Comex Stat,
    usando o endpoint de filtros da própria API.
    """
    resp = request_com_retry('get', f'{COMEX_BASE}/cities/filters/city', params={'state': UF_SC}, timeout=20)
    resp.raise_for_status()
    return resp.json()
