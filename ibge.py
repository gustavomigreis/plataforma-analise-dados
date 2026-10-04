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
}

# --- Agropecuária (PAM - Produção Agrícola Municipal, tabela 5457) e
# (PPM - Pesquisa da Pecuária Municipal, tabela 3939): ambas têm uma
# classificação obrigatória (produto da lavoura / tipo de rebanho) - sem
# especificar uma categoria, o SIDRA devolve só ".." (sem dado), confirmado
# contra a API real (a categoria "0 Total" da PAM está vazia nesta tabela,
# e a PPM não tem "total" nenhum - cada espécie é uma contagem separada).
# Por isso, em vez de um indicador genérico "Quantidade Produzida", o
# catálogo gera um indicador por categoria específica (cada cultura, cada
# tipo de rebanho), agrupados visualmente como um subtema expansível na
# tela de Pesquisa (ver objetos.py SUBGRUPOS) em vez de uma lista plana.

# Todas as culturas da classificação "Produto das lavouras" (c782) da
# tabela 5457, em nível Brasil - confirmado contra a API real (chamada
# direta a t/5457/n1/all/v/214/p/last/c782/all): 128 categorias de produto,
# a lista completa publicada pelo SIDRA, não apenas as que têm produção em
# Santa Catarina. Como a escala "município" da tela de Pesquisa cobre o
# Brasil inteiro quando nenhum filtro de UF/região é escolhido, restringir à
# lista de SC deixava de fora culturas com produção real noutros estados
# (ex: Açaí, Dendê, Guaraná) - cada município sem produção daquela cultura
# simplesmente aparece com valor vazio, o que é esperado, não um erro.
# Terceiro elemento (soma_grupo): False só para "Café (em grão) Arábica" e
# "Café (em grão) Canephora", que são SUBCONJUNTOS de "Café (em grão) Total"
# (confirmado contra a API real: Arábica 2.230.589 + Canephora 1.253.765 =
# Total 3.484.354 t, Brasil 2025) - ficam de fora da soma do indicador-grupo
# "Todas as Culturas" para não contar a produção de café em dobro. Todas as
# demais culturas são independentes entre si nesta tabela.
_PAM_CULTURAS_SC = [
    (40129, 'Abacate', True), (40092, 'Abacaxi', True), (83388, 'Abóbora', True),
    (45982, 'Açaí', True), (83399, 'Acerola', True), (40329, 'Alfafa fenada', True),
    (83389, 'Alface', True), (40130, 'Algodão arbóreo (em caroço)', True),
    (40099, 'Algodão herbáceo (em caroço)', True), (40100, 'Alho', True),
    (40101, 'Amendoim (em casca)', True), (40102, 'Arroz (em casca)', True),
    (40103, 'Aveia (em grão)', True), (40131, 'Azeitona', True),
    (40136, 'Banana (cacho)', True), (40104, 'Batata-doce', True),
    (40105, 'Batata-inglesa', True), (40137, 'Borracha (látex coagulado)', True),
    (40468, 'Borracha (látex líquido)', True), (40138, 'Cacau (em amêndoa)', True),
    (40139, 'Café (em grão) Total', True), (40140, 'Café (em grão) Arábica', False),
    (40141, 'Café (em grão) Canephora', False), (40330, 'Caju', True),
    (40106, 'Cana-de-açúcar', True), (40331, 'Cana para forragem', True),
    (83390, 'Canola', True), (40142, 'Caqui', True), (40143, 'Castanha de caju', True),
    (40107, 'Cebola', True), (83391, 'Cenoura', True), (40108, 'Centeio (em grão)', True),
    (40109, 'Cevada (em grão)', True), (40144, 'Chá-da-índia (folha verde)', True),
    (83392, 'Chuchu', True), (40145, 'Coco-da-baía', True), (83400, 'Cupuaçu', True),
    (40146, 'Dendê (cacho de coco)', True), (40147, 'Erva-mate (folha verde)', True),
    (40110, 'Ervilha (em grão)', True), (40111, 'Fava (em grão)', True),
    (40112, 'Feijão (em grão)', True), (40148, 'Figo', True),
    (40113, 'Fumo (em folha)', True), (83395, 'Gergelim', True),
    (40114, 'Girassol (em grão)', True), (40149, 'Goiaba', True),
    (83401, 'Graviola', True), (40150, 'Guaraná (semente)', True),
    (83393, 'Inhame', True), (40115, 'Juta (fibra)', True), (40151, 'Laranja', True),
    (40152, 'Limão', True), (40116, 'Linho (semente)', True), (40260, 'Maçã', True),
    (40117, 'Malva (fibra)', True), (40261, 'Mamão', True),
    (40118, 'Mamona (baga)', True), (40119, 'Mandioca', True),
    (40262, 'Manga', True), (40263, 'Maracujá', True), (40264, 'Marmelo', True),
    (40120, 'Melancia', True), (40121, 'Melão', True), (40122, 'Milho (em grão)', True),
    (83394, 'Milho verde', True), (83396, 'Morango', True),
    (40265, 'Noz (fruto seco)', True), (40266, 'Palmito', True), (40267, 'Pera', True),
    (40268, 'Pêssego', True), (40269, 'Pimenta-do-reino', True),
    (83397, 'Pimentão', True), (40123, 'Rami (fibra)', True),
    (83398, 'Repolho', True), (40270, 'Sisal ou agave (fibra)', True),
    (40124, 'Soja (em grão)', True), (40125, 'Sorgo (em grão)', True),
    (40271, 'Tangerina', True), (40126, 'Tomate', True),
    (40127, 'Trigo (em grão)', True), (40128, 'Triticale (em grão)', True),
    (40272, 'Tungue (fruto seco)', True), (40273, 'Urucum (semente)', True),
    (40274, 'Uva', True),
]

# Métrica de cada "objeto" PAM gerado por cultura: variável SIDRA + unidade.
# Cada métrica tem seu PRÓPRIO subgrupo (pam_lavouras_<métrica>), não um
# "pam_lavouras" único - área (hectares), valor (mil reais) e quantidade
# (toneladas) não podem ser somadas juntas num mesmo indicador-grupo, cada
# uma precisa do seu próprio "Todas as Culturas".
_PAM_METRICAS = {
    'area_plantada': {'sufixo': 'Área Plantada ou Destinada à Colheita', 'variavel': 8331, 'unidade': 'hectares', 'subgrupo_nome': 'Área Plantada (por cultura)'},
    'valor_producao': {'sufixo': 'Valor da Produção', 'variavel': 215, 'unidade': 'mil reais', 'subgrupo_nome': 'Valor da Produção (por cultura)'},
    'quantidade_produzida': {'sufixo': 'Quantidade Produzida', 'variavel': 214, 'unidade': 'toneladas', 'subgrupo_nome': 'Quantidade Produzida (por cultura)'},
}

for _metrica_chave, _metrica_info in _PAM_METRICAS.items():
    for _cod_cultura, _nome_cultura, _entra_no_total_pam in _PAM_CULTURAS_SC:
        _chave = f'pam_{_metrica_chave}_{_cod_cultura}'
        INDICADORES[_chave] = {
            'nome': f'{_metrica_info["sufixo"]} - {_nome_cultura}',
            'tabela': 5457,
            'variavel': _metrica_info['variavel'],
            'unidade': _metrica_info['unidade'],
            'classificacao': f'c782/{_cod_cultura}',
            # Usado pelo catálogo (objetos.py) para agrupar estes itens como
            # um subtema expansível "Lavouras" em vez de uma lista plana.
            'subgrupo': f'pam_lavouras_{_metrica_chave}',
            'subgrupo_nome': _metrica_info['subgrupo_nome'],
            # False só para Café Arábica/Canephora, subconjuntos de Café
            # Total (ver nota em _PAM_CULTURAS_SC) - todas as demais culturas
            # são independentes entre si e entram na soma do grupo.
            'soma_grupo': _entra_no_total_pam,
        }

# Tipos de rebanho da PPM (tabela 3939, classificação c79) - confirmado
# contra a API real/metadados do SIDRA, são só estas 10 categorias (mais
# "0 Total", que não existe como opção válida nesta tabela). "Suíno -
# matrizes de suínos" e "Galináceos - galinhas" são SUBCONJUNTOS de "Suíno -
# total" e "Galináceos - total" respectivamente (confirmado contra a API
# real: matrizes=1170 cabe dentro de total=4370 na mesma localidade/ano) -
# por isso ficam marcadas como 'soma_grupo': False, para não contar em
# dobro no indicador-grupo "Efetivo de Rebanhos - Todos os tipos" (ver
# _gerar_indicador_grupo abaixo). Continuam aparecendo normalmente como
# opção individual dentro do subgrupo expansível.
_PPM_TIPOS_REBANHO = [
    (2670, 'Bovino', True), (2675, 'Bubalino', True), (2672, 'Equino', True),
    (32794, 'Suíno - total', True), (32795, 'Suíno - matrizes de suínos', False),
    (2681, 'Caprino', True), (2677, 'Ovino', True), (32796, 'Galináceos - total', True),
    (32793, 'Galináceos - galinhas', False), (2680, 'Codornas', True),
]

for _cod_rebanho, _nome_rebanho, _entra_no_total in _PPM_TIPOS_REBANHO:
    _chave = f'ppm_efetivo_{_cod_rebanho}'
    INDICADORES[_chave] = {
        'nome': f'Efetivo de Rebanhos - {_nome_rebanho}',
        'tabela': 3939,
        'variavel': 105,
        'unidade': 'cabeças',
        'classificacao': f'c79/{_cod_rebanho}',
        'subgrupo': 'ppm_criacao',
        'subgrupo_nome': 'Criação (por tipo de rebanho)',
        'soma_grupo': _entra_no_total,
    }

# Para cada subgrupo expansível (Lavouras, Criação), gera um indicador
# "grupo" que soma as categorias marcadas 'soma_grupo': True - é o item que
# aparece como o checkbox PADRÃO do subtema (fora da seta de expandir),
# representando "todas as categorias somadas" sem o usuário precisar abrir
# a lista e marcar uma por uma. SUBGRUPOS guarda, para cada subgrupo, a
# chave do indicador-grupo e a lista de chaves de categoria que ele soma -
# usado por objetos.py tanto para resolver a consulta do grupo (busca cada
# categoria membro e soma) quanto para popular a tela de Pesquisa.
SUBGRUPOS = {}
for _chave_ind, _info_ind in list(INDICADORES.items()):
    _subgrupo = _info_ind.get('subgrupo')
    if not _subgrupo:
        continue
    SUBGRUPOS.setdefault(_subgrupo, {
        'nome': _info_ind['subgrupo_nome'],
        'unidade': _info_ind['unidade'],
        'membros_soma': [],
        'membros_todos': [],
    })
    SUBGRUPOS[_subgrupo]['membros_todos'].append(_chave_ind)
    if _info_ind.get('soma_grupo'):
        SUBGRUPOS[_subgrupo]['membros_soma'].append(_chave_ind)

# Nome de exibição do indicador-grupo por subgrupo (a soma de "Lavouras"
# chama-se "Quantidade Produzida - Todas as Culturas", não um nome
# genérico). Prefixo porque cada métrica PAM tem seu próprio subgrupo
# (pam_lavouras_area_plantada, pam_lavouras_valor_producao, ...).
_NOME_GRUPO_POR_SUBGRUPO = {
    'ppm_criacao': 'Todos os Tipos',
}


def _nome_grupo_padrao(subgrupo_chave):
    if subgrupo_chave in _NOME_GRUPO_POR_SUBGRUPO:
        return _NOME_GRUPO_POR_SUBGRUPO[subgrupo_chave]
    if subgrupo_chave.startswith('pam_lavouras'):
        return 'Todas as Culturas'
    return 'Todas as Categorias'

for _subgrupo_chave, _subgrupo_info in SUBGRUPOS.items():
    _chave_grupo = f'{_subgrupo_chave}_grupo'
    _sufixo_nome = _nome_grupo_padrao(_subgrupo_chave)
    # O nome-base (antes do " - <categoria>") é igual em todo membro do
    # subgrupo (ex: "Quantidade Produzida", "Efetivo de Rebanhos") - usa o
    # primeiro membro como referência para montar o nome do indicador-grupo.
    _nome_base = INDICADORES[_subgrupo_info['membros_todos'][0]]['nome'].rsplit(' - ', 1)[0]
    INDICADORES[_chave_grupo] = {
        'nome': f'{_nome_base} - {_sufixo_nome}',
        'unidade': _subgrupo_info['unidade'],
        # Indicador-grupo não aponta para uma única tabela/variável do SIDRA
        # - é resolvido em objetos.py somando os membros (ver
        # buscar_serie_objeto). 'tabela'/'variavel' ficam None só para
        # manter a mesma forma de dict dos demais indicadores.
        'tabela': None,
        'variavel': None,
        'eh_grupo': True,
        'subgrupo': _subgrupo_chave,
        'subgrupo_nome': _subgrupo_info['nome'],
    }
    SUBGRUPOS[_subgrupo_chave]['chave_indicador_grupo'] = _chave_grupo

# Como agregar o indicador quando o usuário seleciona várias localidades de
# uma vez (ex: Palhoça + Florianópolis + Biguaçu) e pede o valor "aglomerado"
# (em vez de ver cada localidade separada no gráfico): soma faz sentido para
# contagens/totais (população, PIB, nº de empresas, rebanho...), mas não para
# um índice, razão, idade ou percentual (somar "idade mediana" de 3 cidades
# não tem significado) - esses são agregados pela média. Indicador sem
# entrada aqui cai em 'soma' por padrão (a maioria do catálogo é contagem).
AGREGACAO_PADRAO = {
    'indice_envelhecimento': 'media',
    'idade_mediana': 'media',
    'razao_sexo': 'media',
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

# Níveis territoriais aceitos pela API (prefixo "n" + número).
#
# IMPORTANTE sobre 'regiao': o código n24 é "Região Geográfica Intermediária"
# (ex: "Região Geográfica Intermediária de Florianópolis", "de Chapecó", "de
# Lages"), a divisão regional atual do IBGE pós-2017 - NÃO é n2 (que seriam
# as 5 grandes regiões do país, Norte/Nordeste/Sul/Sudeste/Centro-Oeste).
# Confirmado com chamada real à API (tabela do Censo 2022, retornou 165
# registros, um por região intermediária do Brasil).
#
# Nem toda tabela do SIDRA publica dado neste nível - tabelas de estimativas
# anuais (como população estimada, tabela 6579) e o PIB municipal (tabela
# 5938) retornam erro 400 em n24 (confirmado testando diretamente), porque
# essas pesquisas só descem até UF/Município, não têm agregação oficial por
# região intermediária. Isso é uma limitação de cada tabela, não um erro de
# código - a camada de objetos (objetos.py) trata isso como "sem dados
# disponíveis nesta escala" para o indicador em questão, sem quebrar a
# consulta dos demais indicadores selecionados.
NIVEIS = {
    'brasil': 'n1/1',
    'regiao': 'n24/all',  # Região Geográfica Intermediária (ver nota acima)
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
    codigo_localidade: código IBGE da localidade (obrigatório para 'uf' e
                        'municipio'). Pode ser um único código (int/str) ou
                        uma lista de códigos - o SIDRA aceita vários códigos
                        separados por vírgula na mesma consulta (confirmado
                        contra a API real: t/6579/n6/4205407,4202404/v/9324/p/last
                        devolve os dois municípios numa única resposta), o
                        que evita N chamadas separadas para "vários municípios
                        selecionados" ou "todos os municípios de um estado".
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
            # Nenhum código/filtro informado: "(Todos)" - traz todas as
            # localidades do nível de uma vez (ex: todos os ~5.570 municípios
            # do Brasil, ou todas as 27 UFs). Confirmado contra a API real
            # (n6/all devolveu milhares de registros de municípios de vários
            # estados numa única resposta). Antes isso levantava erro exigindo
            # um código específico - mas "nenhum filtro escolhido" é
            # justamente o caso de uso de "(Todos)" na tela de Pesquisa, não
            # um estado inválido.
            localidade = f'{NIVEIS[nivel]}/all'
        elif isinstance(codigo_localidade, dict) and codigo_localidade.get('dentro_de'):
            # "Todos os municípios de uma UF" (ou de uma UF dentro de uma
            # região) sem listar código por código - usa o filtro "in" do
            # SIDRA (sintaxe: n6/in n3 42 = todos os municípios dentro da UF
            # 42). Confirmado contra a API real (retornou 292 municípios de
            # SC de uma vez). Evita montar uma URL com ~300 códigos separados
            # por vírgula quando o usuário só quer "todos os municípios do
            # estado", que além de mais simples evita estourar o limite
            # prático de tamanho de URL.
            nivel_pai, codigo_pai = codigo_localidade['dentro_de']
            localidade = f'{NIVEIS[nivel]}/in%20{nivel_pai}%20{codigo_pai}'
        elif isinstance(codigo_localidade, (list, tuple, set)):
            codigos = ','.join(str(c) for c in codigo_localidade)
            localidade = f'{NIVEIS[nivel]}/{codigos}'
        else:
            localidade = f'{NIVEIS[nivel]}/{codigo_localidade}'
    else:
        raise ValueError(f'Nível territorial desconhecido: {nivel}')

    url = f'{SIDRA_BASE}/t/{tabela}/{localidade}/v/{variavel}/p/{periodo}'
    # Alguns indicadores (ex: PPM - Pesquisa da Pecuária Municipal) têm uma
    # classificação obrigatória (ex: "Tipo de rebanho") sem a qual o SIDRA
    # devolve só ".." em vez do valor - ver nota em INDICADORES['ppm_efetivo_rebanho'].
    classificacao = indicador.get('classificacao')
    if classificacao:
        url += f'/{classificacao}'
    return url


#  "Todos os municípios do Brasil" (n6/all) combinado com "todos os
# períodos" (p/all) estoura um limite de tamanho de resposta do SIDRA -
# confirmado contra a API real: t/5457/n6/all/v/214/p/all/c782/40129 (uma
# única cultura, todos os municípios, todo o histórico) devolve 400, enquanto
# a mesma consulta com p/last funciona normalmente. Isso NÃO é uma categoria
# sem dado (o erro acontece com qualquer cultura/tipo de rebanho quando os
# dois "todos" são combinados ao mesmo tempo) - é só volume de dados grande
# demais para uma resposta só. Quando isso acontece, tenta de novo com um
# período mais estreito em vez de propagar o erro "indisponível".
_PERIODO_FALLBACK_TODOS_MUNICIPIOS = 'last 3'


def buscar_dados(indicador_key, nivel, codigo_localidade=None, periodo='last'):
    """
    Consulta o SIDRA e retorna uma lista de dicts já limpa (sem o cabeçalho
    descritivo que a API sempre retorna como primeiro elemento).

    Cada item tem: localidade, localidade_codigo, periodo, valor, unidade
    """
    url = montar_url(indicador_key, nivel, codigo_localidade, periodo)

    resp = request_com_retry('get', url, timeout=20)
    if resp.status_code == 400:
        # "Todos os municípios" + "todos os períodos" ao mesmo tempo é grande
        # demais para o SIDRA responder de uma vez (ver nota acima) - tenta
        # de novo com uma janela de período mais estreita antes de desistir,
        # em vez de mostrar "indisponível nesta escala" para algo que na
        # verdade está disponível, só não nesse volume.
        if nivel == 'municipio' and not codigo_localidade and periodo == 'all':
            url_fallback = montar_url(indicador_key, nivel, codigo_localidade, _PERIODO_FALLBACK_TODOS_MUNICIPIOS)
            resp_fallback = request_com_retry('get', url_fallback, timeout=20)
            if resp_fallback.status_code != 400:
                resp = resp_fallback
            else:
                raise ValueError(
                    f'O indicador "{INDICADORES.get(indicador_key, {}).get("nome", indicador_key)}" '
                    f'não está disponível nesta escala territorial nesta fonte (SIDRA).'
                )
        else:
            # SIDRA retorna 400 quando a combinação tabela+nível territorial não
            # existe (ex: uma tabela de estimativa anual que não publica dado por
            # região intermediária) - mensagem mais clara que o HTTPError cru.
            raise ValueError(
                f'O indicador "{INDICADORES.get(indicador_key, {}).get("nome", indicador_key)}" '
                f'não está disponível nesta escala territorial nesta fonte (SIDRA).'
            )
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

    Mantida por compatibilidade - buscar_municipios_brasil() é a função usada
    hoje pela tela de Pesquisa (cobre o Brasil inteiro, com a mesma fonte).
    """
    url = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/42/municipios'
    resp = request_com_retry('get', url, timeout=20)
    resp.raise_for_status()
    dados = resp.json()

    return [{'codigo': m['id'], 'nome': m['nome']} for m in dados]


# Cache em memória do processo para buscar_municipios_brasil() - a lista de
# municípios do Brasil não muda durante a vida do processo, e a resposta
# completa (~5.570 municípios) é pesada o bastante (chamada separada da API
# de Localidades, não do SIDRA) para valer a pena não refazer a cada
# consulta - usada tanto pela tela de Pesquisa quanto, agora, pelo fallback
# de agregação por região intermediária (ver _agregar_por_regiao_intermediaria).
_cache_municipios_brasil = None


def buscar_municipios_brasil():
    """
    Retorna todos os municípios do Brasil (cerca de 5.570) com a hierarquia
    territorial completa, usando a API de Localidades do IBGE (endpoint sem
    filtro de UF - confirmado que devolve o país inteiro de uma vez).

    A API tem duas cadeias de hierarquia paralelas para cada município
    (confirmado na estrutura real da resposta):
      - microrregiao -> mesorregiao -> UF -> regiao
      - regiao-imediata -> regiao-intermediaria -> UF -> regiao
    Usamos a segunda (regiao-imediata), que é a divisão territorial mais
    atual do IBGE (substituiu as antigas mesorregiões/microrregiões para
    fins de regionalização, mantidas apenas por compatibilidade histórica).

    Retorna uma lista de dicts: codigo, nome, uf_sigla, uf_nome, regiao_nome,
    regiao_sigla, regiao_imediata_nome. Resultado cacheado em memória (ver
    _cache_municipios_brasil acima).
    """
    global _cache_municipios_brasil
    if _cache_municipios_brasil is not None:
        return _cache_municipios_brasil

    url = 'https://servicodados.ibge.gov.br/api/v1/localidades/municipios'
    resp = request_com_retry('get', url, timeout=60)
    resp.raise_for_status()
    dados = resp.json()

    resultado = []
    for m in dados:
        regiao_imediata = m.get('regiao-imediata') or {}
        regiao_intermediaria = regiao_imediata.get('regiao-intermediaria') or {}
        uf = regiao_intermediaria.get('UF') or {}
        regiao = uf.get('regiao') or {}

        resultado.append({
            'codigo': m.get('id'),
            'nome': m.get('nome'),
            'uf_codigo': uf.get('id'),
            'uf_sigla': uf.get('sigla'),
            'uf_nome': uf.get('nome'),
            'regiao_nome': regiao.get('nome'),
            'regiao_sigla': regiao.get('sigla'),
            'regiao_imediata_nome': regiao_imediata.get('nome'),
            'regiao_imediata_codigo': regiao_imediata.get('id'),
            # Código da região geográfica INTERMEDIÁRIA (nível n24 do SIDRA -
            # ver NIVEIS['regiao'] acima) - necessário para poder filtrar
            # "todos os municípios desta região intermediária" via SIDRA
            # (n6/in n24 <codigo>, confirmado contra a API real) sem ter que
            # listar cada código de município manualmente.
            'regiao_intermediaria_codigo': regiao_intermediaria.get('id'),
            'regiao_intermediaria_nome': regiao_intermediaria.get('nome'),
        })

    _cache_municipios_brasil = resultado
    return resultado


def buscar_dados_agregado_por_regiao(indicador_key, periodo='last'):
    """
    Fallback para quando uma tabela do SIDRA não publica dado em nível de
    região geográfica intermediária (n24) - caso comum em tabelas como PAM e
    PPM (confirmado contra a API real: ambas só vão até Brasil/UF/Município,
    sem região intermediária nem mesorregião/microrregião atualizadas).

    Em vez de mostrar "indisponível nesta escala", busca o dado em nível de
    MUNICÍPIO para o Brasil inteiro (n6/all) e soma os valores de cada
    município dentro da mesma região intermediária, usando a hierarquia de
    buscar_municipios_brasil() para saber a qual região cada município
    pertence. É uma aproximação por agregação ascendente (soma das partes),
    não um dado oficial do IBGE em nível de região - mas é a melhor
    estimativa disponível quando a fonte não publica o nível diretamente.

    Faz sentido para indicadores de CONTAGEM/TOTAL (população, produção,
    efetivo de rebanho, PIB...), que são aditivos; não deveria ser usado
    para índices/razões (não faz sentido "somar" uma idade mediana entre
    municípios - ver ibge.AGREGACAO_PADRAO, a mesma lista usada para decidir
    soma vs. média ao agregar várias localidades selecionadas manualmente).

    Retorna o mesmo formato de buscar_dados(), mas com 'localidade' sendo o
    nome da região intermediária (ex: "Região Geográfica Intermediária de
    Florianópolis") em vez do nome do município.
    """
    dados_municipio = buscar_dados(indicador_key, 'municipio', None, periodo)
    if not dados_municipio:
        return []

    municipios = buscar_municipios_brasil()
    nome_regiao_por_codigo_municipio = {
        str(m['codigo']): m.get('regiao_intermediaria_nome')
        for m in municipios
        if m.get('regiao_intermediaria_nome')
    }

    modo = AGREGACAO_PADRAO.get(indicador_key, 'soma')

    # Agrupa por (região, período) e soma/tira a média dos valores dos
    # municípios dentro de cada região - ignora município sem valor (None)
    # em vez de descartar o período inteiro, e ignora município sem região
    # conhecida (não deveria acontecer, mas não quebra a consulta se faltar
    # um registro na hierarquia de localidades).
    agrupado = {}
    for item in dados_municipio:
        nome_regiao = nome_regiao_por_codigo_municipio.get(str(item['localidade_codigo']))
        if not nome_regiao or item['valor'] is None:
            continue
        chave_grupo = (nome_regiao, item['periodo'])
        agrupado.setdefault(chave_grupo, []).append(item['valor'])

    indicador = INDICADORES[indicador_key]
    resultado = []
    for (nome_regiao, periodo_item), valores in agrupado.items():
        valor_agregado = (sum(valores) / len(valores)) if modo == 'media' else sum(valores)
        resultado.append({
            'localidade': nome_regiao,
            'localidade_codigo': None,
            'periodo': periodo_item,
            'indicador': indicador['nome'],
            'valor': valor_agregado,
            'unidade': indicador['unidade'],
        })

    return resultado
