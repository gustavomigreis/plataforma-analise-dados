"""
Integração com a API pública do IBGE/SIDRA (Sistema IBGE de Recuperação
Automática). Sem necessidade de API key.

Documentação: https://apisidra.ibge.gov.br
"""
from net_utils import request_com_retry

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
    'vab_agropecuaria': {
        'nome': 'VAB Agropecuária (2021)',
        'tabela': 5938,
        'variavel': 513,
        'unidade': 'mil reais',
    },
    'vab_industria': {
        'nome': 'VAB Indústria (2021)',
        'tabela': 5938,
        'variavel': 517,
        'unidade': 'mil reais',
    },
    'vab_servicos': {
        'nome': 'VAB Serviços (2021)',
        'tabela': 5938,
        'variavel': 6575,
        'unidade': 'mil reais',
    },
    'empresas_atuantes': {
        'nome': 'Empresas e Organizações Atuantes',
        'tabela': 9509,
        'variavel': 367,
        'unidade': 'unidades',
    },
    'pessoal_ocupado': {
        'nome': 'Pessoal Ocupado Total',
        'tabela': 9509,
        'variavel': 707,
        'unidade': 'pessoas',
    },

    # --- Ampliação do catálogo (validada contra a API real do SIDRA,
    # testando cada tabela/variável em nível municipal antes de incluir).
    # Demografia (Censo 2022)
    'populacao_censo2022': {
        'nome': 'População Residente (Censo 2022)',
        'tabela': 4709,
        'variavel': 93,
        'unidade': 'pessoas',
    },
    'indice_envelhecimento': {
        'nome': 'Índice de Envelhecimento',
        'tabela': 9515,
        'variavel': 10612,
        'unidade': 'razão (60+/0-14 x100)',
    },
    'idade_mediana': {
        'nome': 'Idade Mediana da População',
        'tabela': 9515,
        'variavel': 10613,
        'unidade': 'anos',
    },
    'razao_sexo': {
        'nome': 'Razão de Sexo',
        'tabela': 9515,
        'variavel': 8845,
        'unidade': 'homens por 100 mulheres',
    },
    # Habitação (Censo 2022) - total de domicílios particulares permanentes
    'domicilios_total': {
        'nome': 'Domicílios Particulares Permanentes Ocupados',
        'tabela': 6892,
        'variavel': 381,
        'unidade': 'domicílios',
    },
    # Agropecuária (PAM - Produção Agrícola Municipal)
    'pam_area_plantada': {
        'nome': 'Área Plantada ou Destinada à Colheita (Lavouras)',
        'tabela': 5457,
        'variavel': 8331,
        'unidade': 'hectares',
    },
    'pam_valor_producao': {
        'nome': 'Valor da Produção Agrícola (Lavouras)',
        'tabela': 5457,
        'variavel': 215,
        'unidade': 'mil reais',
    },
    'pam_quantidade_produzida': {
        'nome': 'Quantidade Produzida (Lavouras)',
        'tabela': 5457,
        'variavel': 214,
        'unidade': 'toneladas',
    },
    # Pecuária (PPM - Pesquisa da Pecuária Municipal)
    'ppm_efetivo_rebanho': {
        'nome': 'Efetivo dos Rebanhos (Pecuária Municipal)',
        'tabela': 3939,
        'variavel': 105,
        'unidade': 'cabeças',
    },
}

# Observações sobre domínios pesquisados e NÃO incluídos no catálogo, porque
# a fonte simplesmente não publica o dado em nível municipal no SIDRA (não é
# uma limitação desta implementação, é da própria base):
# - Saúde (estabelecimentos, leitos): pesquisa AMS do IBGE só tem dado até
#   UF/Região/Brasil; CNES é sistema do DATASUS/Ministério da Saúde, fora do SIDRA.
# - Finanças públicas municipais (receitas/despesas): publicadas pelo Tesouro
#   Nacional via SICONFI, não pelo IBGE/SIDRA.
# - Matrículas e docentes: Censo Escolar é do INEP, fora do SIDRA.
# - Rendimento/ocupação via PNAD Contínua: essa pesquisa não tem nível
#   municipal (só UF/Região Metropolitana/Brasil) - confirmado via teste real.
# - Saneamento por categoria específica (ex: "água de rede geral", "sim"):
#   as tabelas 6803-6805 existem e respondem, mas os códigos de classificação
#   para a categoria específica (além de "Total") não foram confirmados com
#   segurança; por isso não incluídos aqui para evitar mostrar sempre o
#   "Total" rotulado como se fosse a categoria específica.

# Tabelas usadas para montar o "Perfil do Município" (estilo IBGE Cidades).
# Validadas contra a API real; ver notas de cada uma.
_TABELA_AREA = 1301        # Área territorial (Malha do Censo 2010, não muda)
_VAR_AREA = 615             # km²
_VAR_DENSIDADE_CENSO2010 = 616  # densidade do Censo 2010 (desatualizada; recalculamos com pop. atual)

_TABELA_RENDIMENTO = 10295   # Censo 2022 - Rendimento domiciliar per capita
_VAR_RENDIMENTO_MEDIO = 13431
_VAR_RENDIMENTO_MEDIANO = 13534
_CLASS_RENDIMENTO = 'c2/6794/c86/95251/c58/95253'  # fixa sexo/cor/idade = Total

_TABELA_ALFABETIZACAO = 9543  # Censo 2022 - Taxa de alfabetização 15+ anos
_VAR_ALFABETIZACAO = 2513
_CLASS_ALFABETIZACAO = 'c2/6794/c86/95251/c287/100362'  # fixa sexo/cor/idade = Total

# PIB setorial (Valor Adicionado Bruto por setor, preços correntes).
# Mesma tabela do PIB total (5938), mas os VABs setoriais só têm dado
# consolidado até 2021 (2022/2023 retornam vazio na API no momento).
_TABELA_PIB = 5938
_VAR_PIB_TOTAL = 37
_VAR_VAB_AGROPECUARIA = 513
_VAR_VAB_INDUSTRIA = 517
_VAR_VAB_SERVICOS = 6575
_PERIODO_VAB_SETORIAL = '2021'

# Empresas e estabelecimentos (Cadastro Central de Empresas - CEMPRE)
_TABELA_CEMPRE = 9509
_VAR_EMPRESAS_ATUANTES = 367
_VAR_PESSOAL_OCUPADO = 707
_VAR_SALARIOS = 662

# Índice de Gini de renda não está disponível no SIDRA em nível de município
# (confirmado: só existe até UF/Região). Marcado como indisponível no perfil.

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

    resp = request_com_retry('get', url, timeout=20)
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


def _buscar_valor_unico(tabela, variavel, codigo_municipio, classificacoes='', periodo='last'):
    """
    Busca um único valor numérico do SIDRA para um município específico.
    Usada internamente pelo perfil do município. Retorna (valor, periodo) ou (None, None).
    """
    url = f'{SIDRA_BASE}/t/{tabela}/n6/{codigo_municipio}/v/{variavel}/p/{periodo}'
    if classificacoes:
        url += f'/{classificacoes}'

    resp = request_com_retry('get', url, timeout=20)
    resp.raise_for_status()
    dados_brutos = resp.json()

    if not dados_brutos or len(dados_brutos) < 2:
        return None, None

    registro = dados_brutos[1]
    valor_bruto = registro.get('V')
    try:
        valor = float(valor_bruto.replace(',', '.')) if valor_bruto not in (None, '...', '-') else None
    except (ValueError, AttributeError):
        valor = None

    periodo_nome = registro.get('D3N') or registro.get('D2N')
    return valor, periodo_nome


def buscar_perfil_municipio(codigo_municipio):
    """
    Monta um "Perfil do Município" agregando vários indicadores do SIDRA
    em uma única consulta, no estilo do painel do IBGE Cidades.

    Retorna um dict com cada indicador (valor + período + unidade), mais
    indicadores calculados (densidade demográfica, PIB per capita) quando
    os componentes necessários estiverem disponíveis.
    """
    perfil = {}

    # População estimada (anual, mais atual)
    populacao, periodo_pop = _buscar_valor_unico(6579, 9324, codigo_municipio)
    perfil['populacao'] = {'nome': 'População Estimada', 'valor': populacao, 'unidade': 'pessoas', 'periodo': periodo_pop}

    # Área territorial (fixa, Censo 2010 - não muda com frequência)
    area, periodo_area = _buscar_valor_unico(_TABELA_AREA, _VAR_AREA, codigo_municipio)
    perfil['area'] = {'nome': 'Área Territorial', 'valor': area, 'unidade': 'km²', 'periodo': periodo_area}

    # Densidade demográfica: recalculada com população atual / área (mais precisa
    # que a densidade pronta da tabela 1301, que usa população do Censo 2010)
    if populacao and area:
        densidade = round(populacao / area, 2)
        perfil['densidade'] = {'nome': 'Densidade Demográfica', 'valor': densidade, 'unidade': 'hab/km²', 'periodo': periodo_pop}
    else:
        perfil['densidade'] = {'nome': 'Densidade Demográfica', 'valor': None, 'unidade': 'hab/km²', 'periodo': None}

    # PIB municipal
    pib, periodo_pib = _buscar_valor_unico(5938, 37, codigo_municipio)
    perfil['pib'] = {'nome': 'PIB Municipal', 'valor': pib, 'unidade': 'mil reais', 'periodo': periodo_pib}

    # PIB per capita: calculado (PIB está em mil reais, então o resultado já sai em reais)
    if pib and populacao:
        pib_per_capita = round((pib * 1000) / populacao, 2)
        perfil['pib_per_capita'] = {'nome': 'PIB per Capita', 'valor': pib_per_capita, 'unidade': 'reais', 'periodo': periodo_pib}
    else:
        perfil['pib_per_capita'] = {'nome': 'PIB per Capita', 'valor': None, 'unidade': 'reais', 'periodo': None}

    # Rendimento domiciliar per capita (Censo 2022)
    rendimento, periodo_rend = _buscar_valor_unico(
        _TABELA_RENDIMENTO, _VAR_RENDIMENTO_MEDIO, codigo_municipio, _CLASS_RENDIMENTO
    )
    perfil['rendimento_medio'] = {'nome': 'Rendimento Domiciliar Médio per Capita', 'valor': rendimento, 'unidade': 'reais', 'periodo': periodo_rend}

    # Taxa de alfabetização (Censo 2022)
    alfabetizacao, periodo_alfa = _buscar_valor_unico(
        _TABELA_ALFABETIZACAO, _VAR_ALFABETIZACAO, codigo_municipio, _CLASS_ALFABETIZACAO
    )
    perfil['alfabetizacao'] = {'nome': 'Taxa de Alfabetização (15+ anos)', 'valor': alfabetizacao, 'unidade': '%', 'periodo': periodo_alfa}

    # PIB setorial (Valor Adicionado Bruto por setor) - dados mais recentes consolidados são de 2021
    vab_agro, periodo_vab = _buscar_valor_unico(_TABELA_PIB, _VAR_VAB_AGROPECUARIA, codigo_municipio, periodo=_PERIODO_VAB_SETORIAL)
    perfil['vab_agropecuaria'] = {'nome': 'VAB Agropecuária', 'valor': vab_agro, 'unidade': 'mil reais', 'periodo': periodo_vab}

    vab_industria, _ = _buscar_valor_unico(_TABELA_PIB, _VAR_VAB_INDUSTRIA, codigo_municipio, periodo=_PERIODO_VAB_SETORIAL)
    perfil['vab_industria'] = {'nome': 'VAB Indústria', 'valor': vab_industria, 'unidade': 'mil reais', 'periodo': periodo_vab}

    vab_servicos, _ = _buscar_valor_unico(_TABELA_PIB, _VAR_VAB_SERVICOS, codigo_municipio, periodo=_PERIODO_VAB_SETORIAL)
    perfil['vab_servicos'] = {'nome': 'VAB Serviços', 'valor': vab_servicos, 'unidade': 'mil reais', 'periodo': periodo_vab}

    # Empresas e estabelecimentos (CEMPRE)
    empresas, periodo_cempre = _buscar_valor_unico(_TABELA_CEMPRE, _VAR_EMPRESAS_ATUANTES, codigo_municipio)
    perfil['empresas_atuantes'] = {'nome': 'Empresas e Organizações Atuantes', 'valor': empresas, 'unidade': 'unidades', 'periodo': periodo_cempre}

    pessoal_ocupado, _ = _buscar_valor_unico(_TABELA_CEMPRE, _VAR_PESSOAL_OCUPADO, codigo_municipio)
    perfil['pessoal_ocupado'] = {'nome': 'Pessoal Ocupado Total', 'valor': pessoal_ocupado, 'unidade': 'pessoas', 'periodo': periodo_cempre}

    salarios, _ = _buscar_valor_unico(_TABELA_CEMPRE, _VAR_SALARIOS, codigo_municipio)
    perfil['salarios'] = {'nome': 'Salários e Outras Remunerações', 'valor': salarios, 'unidade': 'mil reais', 'periodo': periodo_cempre}

    # Índice de Gini: não existe no SIDRA em nível de município (só até UF/Região).
    # Marcado explicitamente como indisponível em vez de omitido silenciosamente.
    perfil['gini'] = {'nome': 'Índice de Gini (Renda)', 'valor': None, 'unidade': '', 'periodo': 'Indisponível no SIDRA para nível municipal'}

    return perfil


def buscar_municipios_sc():
    """
    Retorna a lista de municípios de Santa Catarina (código IBGE + nome),
    usando a API de Localidades do IBGE (separada do SIDRA, mas também pública).
    """
    url = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/42/municipios'
    resp = request_com_retry('get', url, timeout=20)
    resp.raise_for_status()
    dados = resp.json()

    return [{'codigo': m['id'], 'nome': m['nome']} for m in dados]
