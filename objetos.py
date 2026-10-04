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

# Escalas territoriais suportadas pela pesquisa unificada. Nem todo objeto
# está disponível em toda escala (ver ESCALAS_POR_FONTE abaixo).
ESCALAS = {
    'brasil': 'Brasil',
    'regiao': 'Região',
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
        }

    for chave, info in bcb.INDICADORES.items():
        catalogo[f'bcb:{chave}'] = {
            'fonte': 'bcb',
            'chave_fonte': chave,
            'nome': info['nome'],
            'unidade': info['unidade'],
            'escalas': sorted(ESCALAS_POR_FONTE['bcb']),
        }

    # Comex Stat não é um catálogo de variáveis fixas como os outros - é uma
    # combinação de fluxo (export/import) x métrica. Expomos as combinações
    # mais úteis como "objetos" para manter a mesma interface de seleção.
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
            }

    return catalogo


CATALOGO = _construir_catalogo()


def listar_objetos(escala=None):
    """
    Lista os objetos do catálogo, opcionalmente filtrados por escala
    territorial (só retorna objetos disponíveis naquela escala).
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
        })
    return sorted(itens, key=lambda x: (x['fonte'], x['nome']))


def _nivel_ibge(escala):
    """Traduz a escala genérica para a chave de NIVEIS usada em ibge.py."""
    if escala not in ibge.NIVEIS:
        raise ValueError(f'Escala "{escala}" não suportada pelo IBGE/SIDRA')
    return escala


def buscar_serie_objeto(chave_objeto, escala, codigo_localidade=None, periodo='last',
                         ano_inicio=None, ano_fim=None):
    """
    Busca os dados de um objeto do catálogo numa escala/localidade dada,
    devolvendo um formato comum independente da fonte:

        {'objeto': chave_objeto, 'nome': ..., 'unidade': ..., 'fonte': ...,
         'serie': [{'localidade': ..., 'periodo': ..., 'valor': ...}, ...]}

    codigo_localidade: necessário para escala 'uf' ou 'municipio' (código
                        IBGE da UF/município). Ignorado para 'brasil'/'regiao'.
    periodo: usado pela consulta ao SIDRA ('last', 'last 5', ano específico).
    ano_inicio/ano_fim: usados pela consulta ao Comex Stat (strings 'YYYY').
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
        dados = ibge.buscar_dados(info['chave_fonte'], nivel, codigo_localidade, periodo)
        serie = [
            {'localidade': d['localidade'], 'periodo': d['periodo'], 'valor': d['valor']}
            for d in dados
        ]

    elif fonte == 'bcb':
        # BCB é sempre série nacional - localidade fixa "Brasil".
        quantidade = 24
        dados = bcb.buscar_serie(info['chave_fonte'], quantidade=quantidade)
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
        cod_mun = codigo_localidade if escala == 'municipio' else None
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

    return {
        'objeto': chave_objeto,
        'nome': info['nome'],
        'unidade': info['unidade'],
        'fonte': fonte,
        'serie': serie,
    }
