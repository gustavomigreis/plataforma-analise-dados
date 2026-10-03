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
import requests

COMEX_BASE = 'https://api-comexstat.mdic.gov.br'

# Código do IBGE/Comex para Santa Catarina (usa o mesmo código de UF = 42)
UF_SC = 42

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

    resp = requests.post(f'{COMEX_BASE}/cities', json=payload, timeout=30)
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
            municipio = nome_mun_uf.rsplit(' - ', 1)[0]
        else:
            municipio = 'Desconhecido'

        resultado.append({
            'municipio': municipio,
            'valor_fob_usd': item.get('metricFOB'),
            'peso_liquido_kg': item.get('metricKG'),
            'fluxo': fluxo,
            'periodo': f'{ano_inicio}-{ano_fim}',
        })

    return resultado


def listar_municipios_disponiveis_sc():
    """
    Lista os municípios de SC com dados disponíveis no Comex Stat,
    usando o endpoint de filtros da própria API.
    """
    resp = requests.get(f'{COMEX_BASE}/cities/filters/city', params={'state': UF_SC}, timeout=20)
    resp.raise_for_status()
    return resp.json()
