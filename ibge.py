"""
Integração com a API pública do IBGE/SIDRA (Sistema IBGE de Recuperação
Automática). Sem necessidade de API key.

Documentação: https://apisidra.ibge.gov.br
"""
import requests

SIDRA_BASE = 'https://apisidra.ibge.gov.br/values'

# Indicadores pré-configurados mais úteis para análise geográfica/econômica.
# Cada um aponta para uma tabela e variável específica do SIDRA.
INDICADORES = {
    'populacao': {
        'nome': 'População Estimada',
        'tabela': 6579,
        'variavel': 9324,
        'unidade': 'pessoas',
    },
    'pib_municipal': {
        'nome': 'PIB a Preços Correntes',
        'tabela': 5938,
        'variavel': 37,
        'unidade': 'mil reais',
    },
    'pib_per_capita': {
        'nome': 'PIB per Capita',
        'tabela': 5938,
        'variavel': 498,
        'unidade': 'reais',
    },
}

# Níveis territoriais aceitos pela API (prefixo "n" + número)
NIVEIS = {
    'brasil': 'n1/1',
    'regiao': 'n2/all',
    'uf': 'n3',          # precisa de código da UF (ex: 42 = SC)
    'municipio': 'n6',    # precisa de código do município (ex: 4205407 = Florianópolis)
}

# Código do IBGE para Santa Catarina
UF_SC = 42


def montar_url(indicador_key, nivel, codigo_localidade=None, periodo='last'):
    """
    Monta a URL de consulta ao SIDRA.

    indicador_key: uma chave de INDICADORES (ex: 'populacao')
    nivel: uma chave de NIVEIS (ex: 'municipio', 'uf')
    codigo_localidade: código IBGE da localidade (obrigatório para 'uf' e 'municipio')
    periodo: 'last', 'last 5', ou um ano específico como '2022'
    """
    if indicador_key not in INDICADORES:
        raise ValueError(f'Indicador desconhecido: {indicador_key}')

    indicador = INDICADORES[indicador_key]
    tabela = indicador['tabela']
    variavel = indicador['variavel']

    if nivel in ('brasil',):
        localidade = NIVEIS['brasil']
    elif nivel == 'regiao':
        localidade = NIVEIS['regiao']
    elif nivel in ('uf', 'municipio'):
        if not codigo_localidade:
            raise ValueError(f'nível "{nivel}" exige codigo_localidade')
        localidade = f'{NIVEIS[nivel]}/{codigo_localidade}'
    else:
        raise ValueError(f'Nível territorial desconhecido: {nivel}')

    url = f'{SIDRA_BASE}/t/{tabela}/{localidade}/v/{variavel}/p/{periodo}'
    return url


def buscar_dados(indicador_key, nivel, codigo_localidade=None, periodo='last'):
    """
    Consulta o SIDRA e retorna uma lista de dicts já limpa (sem o cabeçalho
    descritivo que a API sempre retorna como primeiro elemento).

    Cada item tem: localidade, localidade_codigo, periodo, valor, unidade
    """
    url = montar_url(indicador_key, nivel, codigo_localidade, periodo)

    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    dados_brutos = resp.json()

    if not dados_brutos or len(dados_brutos) < 2:
        return []

    # O primeiro item é sempre o dicionário de descrição dos campos; ignoramos.
    registros = dados_brutos[1:]

    indicador = INDICADORES[indicador_key]
    resultado = []
    for r in registros:
        try:
            valor = float(r.get('V', '').replace(',', '.')) if r.get('V') not in (None, '...', '-') else None
        except (ValueError, AttributeError):
            valor = None

        resultado.append({
            'localidade': r.get('D1N') or r.get('NN'),
            'localidade_codigo': r.get('D1C') or r.get('NC'),
            'periodo': r.get('D3N') or r.get('D2N'),
            'indicador': indicador['nome'],
            'valor': valor,
            'unidade': indicador['unidade'],
        })

    return resultado


def buscar_municipios_sc():
    """
    Retorna a lista de municípios de Santa Catarina (código IBGE + nome),
    usando a API de Localidades do IBGE (separada do SIDRA, mas também pública).
    """
    url = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/42/municipios'
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    dados = resp.json()

    return [{'codigo': m['id'], 'nome': m['nome']} for m in dados]
