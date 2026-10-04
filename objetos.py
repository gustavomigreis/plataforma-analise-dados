"""
Catálogo unificado de "objetos" (indicadores/variáveis) disponíveis para
análise, agregando as três fontes de dados da plataforma: IBGE/SIDRA, Banco
Central (BCB) e Comex Stat (MDIC).

Pensado para alimentar a tela de Pesquisa: o usuário escolhe uma escala
territorial e um ou mais objetos, e esta camada resolve cada objeto para a
fonte certa, chamando a função de busca apropriada e devolvendo um formato
comum (lista de {localidade, periodo, valor}), independente de a série vir
do SIDRA, do SGS do BCB ou do Comex Stat.

Esta é a camada de integração - não reimplementa nenhuma consulta, apenas
orquestra ibge.py, bcb.py e comexstat.py sob uma interface única.
"""
import ibge
import bcb
import comexstat

# Janela padrão (em registros mensais) buscada do BCB/SGS para a tela de
# Pesquisa - 10 anos de histórico, para dar uma série de verdade ao gráfico.
BCB_QUANTIDADE_PADRAO = 120

# Escalas territoriais suportadas pela pesquisa unificada. Nem todo objeto
# está disponível em toda escala (ver ESCALAS_POR_FONTE abaixo).
ESCALAS = {
    'brasil': 'Brasil',
    'regiao': 'Região Geográfica Intermediária',
    'uf': 'Unidade Federativa',
    'municipio': 'Município',
}

# Cada fonte tem suas próprias limitações de granularidade territorial:
# - IBGE/SIDRA: Brasil, Região, UF e Município (depende da tabela - algumas
#   tabelas do Censo só têm município; ver ibge.NIVEIS).
# - BCB/SGS: é sempre uma série NACIONAL agregada - não existe Selic ou IPCA
#   "do município X". Então só aceita escala 'brasil'.
# - Comex Stat: os dados desta plataforma são filtrados para Santa Catarina
#   (UF fixa), então as escalas úteis são 'uf' (agregado SC) e 'municipio'
#   (por município de SC). Não tem Brasil/Região neste recorte do projeto.
ESCALAS_POR_FONTE = {
    'ibge': {'brasil', 'regiao', 'uf', 'municipio'},
    'bcb': {'brasil'},
    'comex': {'uf', 'municipio'},
}

# Temas de conteúdo, usados para agrupar o catálogo de objetos na tela de
# Pesquisa em "caixas" de assunto, em vez de por fonte - um objeto de
# qualquer fonte pode cair no mesmo tema (ex: câmbio do BCB e comércio
# exterior do Comex Stat, ambos sob "Comércio Exterior e Câmbio").
TEMAS = {
    'demografia': 'Demografia',
    'economia_producao': 'Economia e Produção',
    'trabalho_renda': 'Trabalho, Renda e Empresas',
    'agropecuaria': 'Agropecuária',
    'habitacao': 'Habitação',
    'precos_inflacao': 'Preços e Inflação',
    'juros_moeda': 'Juros e Moeda',
    'financas_publicas': 'Finanças Públicas',
    'comercio_exterior': 'Comércio Exterior e Câmbio',
}

# Mapeia cada objeto (pela chave na fonte, antes do prefixo "fonte:") para
# seu tema. Um objeto sem entrada aqui cai em "outros" (ver _construir_catalogo).
_TEMA_POR_CHAVE_IBGE = {
    'populacao': 'demografia',
    'populacao_censo2022': 'demografia',
    'indice_envelhecimento': 'demografia',
    'idade_mediana': 'demografia',
    'razao_sexo': 'demografia',
    'pib_municipal': 'economia_producao',
    'vab_agropecuaria': 'agropecuaria',
    'vab_industria': 'economia_producao',
    'vab_servicos': 'economia_producao',
    'empresas_atuantes': 'trabalho_renda',
    'pessoal_ocupado': 'trabalho_renda',
    'domicilios_total': 'habitacao',
}

# Prefixos de chave que caem em "agropecuária" por padrão - usado para o PAM
# (pam_area_plantada_<código>, pam_valor_producao_<código>,
# pam_quantidade_produzida_<código>, um por cultura) e a PPM
# (ppm_efetivo_<código>, um por tipo de rebanho), gerados dinamicamente em
# ibge.py (um indicador fixo por categoria ficaria defasado a cada nova
# cultura/rebanho adicionado ao catálogo).
_PREFIXOS_TEMA_IBGE = {
    'pam_': 'agropecuaria',
    'ppm_': 'agropecuaria',
}


def _tema_ibge(chave):
    if chave in _TEMA_POR_CHAVE_IBGE:
        return _TEMA_POR_CHAVE_IBGE[chave]
    for prefixo, tema in _PREFIXOS_TEMA_IBGE.items():
        if chave.startswith(prefixo):
            return tema
    return 'outros'

_TEMA_POR_CHAVE_BCB = {
    'selic_meta': 'juros_moeda',
    'selic_over': 'juros_moeda',
    'cdi': 'juros_moeda',
    'tjlp': 'juros_moeda',
    'cambio_usd': 'comercio_exterior',
    'ipca_mensal': 'precos_inflacao',
    'ipca_12_meses': 'precos_inflacao',
    'igp_m': 'precos_inflacao',
    'inpc_mensal': 'precos_inflacao',
    'divida_pib': 'financas_publicas',
    'ibc_br': 'economia_producao',
}


def _construir_catalogo():
    """
    Monta o catálogo de objetos a partir dos três módulos de fonte,
    prefixando cada chave com a fonte para evitar colisão de nomes
    (ex: 'ibge:populacao', 'bcb:selic_meta', 'comex:exportacao_fob').
    """
    catalogo = {}

    for chave, info in ibge.INDICADORES.items():
        catalogo[f'ibge:{chave}'] = {
            'fonte': 'ibge',
            'chave_fonte': chave,
            'nome': info['nome'],
            'unidade': info['unidade'],
            'escalas': sorted(ESCALAS_POR_FONTE['ibge']),
            'tema': _tema_ibge(chave),
            # Indicadores gerados por categoria (uma cultura, um tipo de
            # rebanho) trazem 'subgrupo'/'subgrupo_nome' de ibge.py, usados
            # pela tela de Pesquisa para agrupá-los num subtema expansível
            # dentro do tema (ex: "Lavouras (por cultura)" dentro de
            # Agropecuária) em vez de uma lista plana de dezenas de opções.
            'subgrupo': info.get('subgrupo'),
            'subgrupo_nome': info.get('subgrupo_nome'),
        }

    for chave, info in bcb.INDICADORES.items():
        catalogo[f'bcb:{chave}'] = {
            'fonte': 'bcb',
            'chave_fonte': chave,
            'nome': info['nome'],
            'unidade': info['unidade'],
            'escalas': sorted(ESCALAS_POR_FONTE['bcb']),
            'tema': _TEMA_POR_CHAVE_BCB.get(chave, 'outros'),
        }

    # Comex Stat não é um catálogo de variáveis fixas como os outros - é uma
    # combinação de fluxo (export/import) x métrica. Expomos as combinações
    # mais úteis como "objetos" para manter a mesma interface de seleção.
    # Todas caem no tema "Comércio Exterior e Câmbio", junto com câmbio do BCB.
    for fluxo_chave, fluxo_nome in (('exportacao', 'Exportações'), ('importacao', 'Importações')):
        for metrica_chave in ('fob', 'kg'):
            chave = f'comex:{fluxo_chave}_{metrica_chave}'
            nome_metrica = 'Valor FOB (US$)' if metrica_chave == 'fob' else 'Peso Líquido (kg)'
            catalogo[chave] = {
                'fonte': 'comex',
                'chave_fonte': {'fluxo': fluxo_chave, 'metrica': metrica_chave},
                'nome': f'{fluxo_nome} - {nome_metrica}',
                'unidade': 'US$' if metrica_chave == 'fob' else 'kg',
                'escalas': sorted(ESCALAS_POR_FONTE['comex']),
                'tema': 'comercio_exterior',
            }

    return catalogo


CATALOGO = _construir_catalogo()


def listar_objetos(escala=None):
    """
    Lista os objetos do catálogo, opcionalmente filtrados por escala
    territorial (só retorna objetos disponíveis naquela escala). Ordenado
    por tema (as "caixas" exibidas na tela de Pesquisa), depois por nome.
    """
    itens = []
    for chave, info in CATALOGO.items():
        if escala and escala not in info['escalas']:
            continue
        itens.append({
            'chave': chave,
            'fonte': info['fonte'],
            'nome': info['nome'],
            'unidade': info['unidade'],
            'escalas': info['escalas'],
            'tema': info['tema'],
            'tema_nome': TEMAS.get(info['tema'], 'Outros'),
            'subgrupo': info.get('subgrupo'),
            'subgrupo_nome': info.get('subgrupo_nome'),
        })
    return sorted(itens, key=lambda x: (x['tema_nome'], x.get('subgrupo_nome') or '', x['nome']))


def _nivel_ibge(escala):
    """Traduz a escala genérica para a chave de NIVEIS usada em ibge.py."""
    if escala not in ibge.NIVEIS:
        raise ValueError(f'Escala "{escala}" não suportada pelo IBGE/SIDRA')
    return escala


def _modo_agregacao(chave_objeto, info):
    """
    Decide se várias localidades selecionadas juntas devem ser agregadas por
    soma ou por média, quando o usuário pede o valor "aglomerado" em vez de
    ver cada localidade separada. Contagens/totais (população, PIB,
    exportações...) somam; índices/razões/idades fazem média. Câmbio e outras
    séries do BCB não têm localidade múltipla (são sempre nacionais), então
    isso não se aplica a elas.
    """
    if info['fonte'] == 'ibge':
        return ibge.AGREGACAO_PADRAO.get(info['chave_fonte'], 'soma')
    if info['fonte'] == 'comex':
        return 'soma'
    return 'soma'


def _agregar_serie(serie, modo):
    """
    Colapsa uma série com várias localidades por período num único ponto por
    período (rótulo "Selecão agregada (N localidades)"), somando ou tirando a
    média dos valores de cada localidade naquele período. Períodos onde nem
    toda localidade tem valor ainda entram no cálculo (ignora None), já que
    exigir cobertura total descartaria períodos só porque uma localidade
    started reporting depois - mais útil mostrar o agregado parcial do que
    nada.
    """
    por_periodo = {}
    localidades_por_periodo = {}
    for item in serie:
        periodo = item['periodo']
        valor = item['valor']
        if valor is None:
            continue
        por_periodo.setdefault(periodo, []).append(valor)
        localidades_por_periodo.setdefault(periodo, set()).add(item['localidade'])

    total_localidades = len({item['localidade'] for item in serie})
    agregada = []
    for periodo, valores in por_periodo.items():
        if modo == 'media':
            valor_agregado = sum(valores) / len(valores)
        else:
            valor_agregado = sum(valores)
        n_localidades = len(localidades_por_periodo[periodo])
        rotulo = f'Seleção agregada ({n_localidades} de {total_localidades} localidades)'
        agregada.append({'localidade': rotulo, 'periodo': periodo, 'valor': valor_agregado})

    return agregada


def buscar_serie_objeto(chave_objeto, escala, codigo_localidade=None, periodo='last',
                         ano_inicio=None, ano_fim=None, agregar=False):
    """
    Busca os dados de um objeto do catálogo numa escala/localidade dada,
    devolvendo um formato comum independente da fonte:

        {'objeto': chave_objeto, 'nome': ..., 'unidade': ..., 'fonte': ...,
         'serie': [{'localidade': ..., 'periodo': ..., 'valor': ...}, ...],
         'serie_agregada': [...] ou None,
         'modo_agregacao': 'soma' | 'media' | None}

    codigo_localidade: necessário para escala 'uf' ou 'municipio'. Pode ser:
                        - um único código (int/str): uma localidade;
                        - uma lista de códigos: várias localidades
                          selecionadas manualmente (ex: Palhoça + Florianópolis);
                        - None: todas as localidades disponíveis na escala
                          (todos os municípios do Brasil/da UF filtrada, ver
                          'dentro_de' abaixo) - a opção "(Todos)" dos filtros;
                        - {'dentro_de': (nivel_pai, codigo_pai)}: todas as
                          localidades dentro de uma UF ou região intermediária
                          (ex: {'dentro_de': ('n3', 42)} = todos os municípios
                          de SC), sem precisar listar cada código.
                        Ignorado para 'brasil'/'regiao'.
    periodo: usado pela consulta ao SIDRA ('last', 'last 5', ano específico).
    ano_inicio/ano_fim: usados pela consulta ao Comex Stat (strings 'YYYY').
    agregar: quando True e há mais de uma localidade na série resultante,
             também devolve 'serie_agregada' com um único ponto por período
             (soma ou média, conforme o indicador - ver _modo_agregacao).
             A série original (por localidade) sempre é devolvida também, para
             permitir alternar entre a visão agregada e a separada no mesmo
             gráfico sem nova consulta.
    """
    if chave_objeto not in CATALOGO:
        raise ValueError(f'Objeto desconhecido: {chave_objeto}')

    info = CATALOGO[chave_objeto]
    fonte = info['fonte']

    if escala not in info['escalas']:
        raise ValueError(
            f'Objeto "{chave_objeto}" não está disponível na escala "{escala}". '
            f'Escalas disponíveis: {", ".join(info["escalas"])}'
        )

    if fonte == 'ibge':
        nivel = _nivel_ibge(escala)
        try:
            dados = ibge.buscar_dados(info['chave_fonte'], nivel, codigo_localidade, periodo)
        except ValueError:
            # Tabela não publica este indicador em nível de região
            # intermediária (comum em PAM/PPM - confirmado contra a API
            # real). Em vez de propagar o erro "indisponível nesta escala",
            # soma/agrega o dado a partir dos municípios de cada região -
            # ver ibge.buscar_dados_agregado_por_regiao. Só faz sentido para
            # a escala 'regiao' (não há fallback ascendente sensato para
            # 'uf' ou 'brasil' a partir de milhares de municípios de uma vez
            # sem um filtro territorial, e essas escalas normalmente já têm
            # dado direto da fonte quando município tem).
            if nivel != 'regiao':
                raise
            dados = ibge.buscar_dados_agregado_por_regiao(info['chave_fonte'], periodo)
        serie = [
            {'localidade': d['localidade'], 'periodo': d['periodo'], 'valor': d['valor']}
            for d in dados
        ]

    elif fonte == 'bcb':
        # BCB é sempre série nacional - localidade fixa "Brasil". Pede uma
        # janela ampla (10 anos de dados mensais) em vez de só os últimos 24
        # registros, para mostrar o histórico disponível no gráfico por
        # padrão (BCB/SGS não tem um equivalente direto a "todos os
        # períodos" como o SIDRA tem com p/all).
        dados = bcb.buscar_serie(info['chave_fonte'], quantidade=BCB_QUANTIDADE_PADRAO)
        serie = [
            {'localidade': 'Brasil', 'periodo': d['periodo'], 'valor': d['valor']}
            for d in dados
        ]

    elif fonte == 'comex':
        if not ano_inicio or not ano_fim:
            raise ValueError('Objetos do Comex Stat exigem ano_inicio e ano_fim')
        fluxo = info['chave_fonte']['fluxo']
        metrica = info['chave_fonte']['metrica']
        detalhamento = 'municipio' if escala == 'municipio' else 'uf'
        # 'dentro_de' não se aplica ao Comex Stat (a consulta já é sempre
        # restrita à UF fixa do projeto) - só passa adiante código único ou
        # lista de códigos de município.
        cod_mun = None
        if escala == 'municipio' and isinstance(codigo_localidade, dict):
            cod_mun = None  # "(Todos)" - comportamento padrão da função já traz a UF inteira
        elif escala == 'municipio':
            cod_mun = codigo_localidade
        registros = comexstat.buscar_comercio_exterior(
            fluxo, ano_inicio, ano_fim, codigo_municipio=cod_mun,
            detalhamento=detalhamento, metricas=(metrica,)
        )
        serie = [
            {'localidade': r['rotulo'], 'periodo': r['periodo'], 'valor': r.get(metrica)}
            for r in registros
        ]

    else:
        raise ValueError(f'Fonte desconhecida: {fonte}')

    resultado = {
        'objeto': chave_objeto,
        'nome': info['nome'],
        'unidade': info['unidade'],
        'fonte': fonte,
        'serie': serie,
        'serie_agregada': None,
        'modo_agregacao': None,
    }

    localidades_distintas = {item['localidade'] for item in serie}
    if agregar and len(localidades_distintas) > 1:
        modo = _modo_agregacao(chave_objeto, info)
        resultado['serie_agregada'] = _agregar_serie(serie, modo)
        resultado['modo_agregacao'] = modo

    return resultado
