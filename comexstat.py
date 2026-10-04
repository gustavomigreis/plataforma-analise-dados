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

# Métricas disponíveis na API (confirmado contra a documentação oficial,
# doc.yaml do Comex Stat). metricCIF/metricFreight/metricInsurance só têm
# sentido para importação (não existem no fluxo de exportação).
METRICAS_DISPONIVEIS = {
    'fob': 'metricFOB',          # valor no embarque, sem frete/seguro (export e import)
    'kg': 'metricKG',            # peso líquido em kg (export e import)
    'cif': 'metricCIF',          # valor com frete+seguro (somente import)
    'frete': 'metricFreight',    # valor do frete declarado (somente import)
    'seguro': 'metricInsurance',  # valor do seguro declarado (somente import)
    'quantidade_estatistica': 'metricStatistic',  # quantidade na unidade estatística do produto
}

# Detalhamentos (agrupamentos) disponíveis para a consulta, além de 'city'.
DETALHAMENTOS_DISPONIVEIS = {
    'municipio': 'city',
    'pais': 'country',           # país parceiro (origem na importação, destino na exportação)
    'uf': 'state',
    'ncm': 'ncm',                 # produto (Nomenclatura Comum do Mercosul)
    'bloco_economico': 'economicBlock',
    'via_transporte': 'viaTransport',
    'secao': 'section',           # seção do Sistema Harmonizado
    'urf': 'urf',                 # unidade da Receita Federal que processou
}


def buscar_comercio_exterior(fluxo, ano_inicio, ano_fim, codigo_municipio=None, uf=UF_SC,
                              detalhamento='municipio', metricas=('fob', 'kg')):
    """
    Consulta a API do Comex Stat para exportações ou importações.

    fluxo: 'exportacao' ou 'importacao'
    ano_inicio, ano_fim: strings 'YYYY' (ex: '2023', '2024')
    codigo_municipio: código IBGE do município (opcional - se None, traz todos os
                       municípios da UF). Aceita também uma lista de códigos para
                       filtrar por vários municípios de uma vez (ex: Palhoça +
                       Florianópolis + Biguaçu) - a API do Comex Stat já aceita
                       múltiplos valores no mesmo filtro 'city'.
    uf: código da UF (padrão: Santa Catarina)
    detalhamento: chave de DETALHAMENTOS_DISPONIVEIS - define o agrupamento
                  dos resultados (padrão: por município, comportamento original)
    metricas: tupla de chaves de METRICAS_DISPONIVEIS a retornar (padrão: FOB e KG,
              comportamento original). metricCIF/frete/seguro só se aplicam a
              importação - pedi-las numa consulta de exportação simplesmente
              não retorna a coluna (a API as ignora nesse fluxo).

    Retorna uma lista de dicts: município (ou outro agrupamento conforme
    'detalhamento'), as métricas pedidas, fluxo e período.
    """
    if fluxo not in FLUXOS:
        raise ValueError(f'Fluxo inválido: {fluxo}. Use "exportacao" ou "importacao"')
    if detalhamento not in DETALHAMENTOS_DISPONIVEIS:
        raise ValueError(f'Detalhamento inválido: {detalhamento}. Opções: {", ".join(DETALHAMENTOS_DISPONIVEIS)}')
    metricas_invalidas = [m for m in metricas if m not in METRICAS_DISPONIVEIS]
    if metricas_invalidas:
        raise ValueError(f'Métrica(s) inválida(s): {metricas_invalidas}. Opções: {", ".join(METRICAS_DISPONIVEIS)}')

    filtros = [{'filter': 'state', 'values': [str(uf)]}]
    if codigo_municipio:
        if isinstance(codigo_municipio, (list, tuple, set)):
            valores_municipio = [str(c) for c in codigo_municipio]
        else:
            valores_municipio = [str(codigo_municipio)]
        filtros.append({'filter': 'city', 'values': valores_municipio})

    campo_detalhe = DETALHAMENTOS_DISPONIVEIS[detalhamento]
    campos_metricas = [METRICAS_DISPONIVEIS[m] for m in metricas]

    payload = {
        'flow': FLUXOS[fluxo],
        'monthDetail': False,
        'period': {'from': f'{ano_inicio}-01', 'to': f'{ano_fim}-12'},
        'filters': filtros,
        'details': [campo_detalhe],
        'metrics': campos_metricas,
    }

    # O endpoint /cities só suporta detalhamento por município/UF/país (é o
    # mais agregado). Detalhamentos mais finos (NCM, via de transporte, seção
    # do SH, URF, bloco econômico) exigem o endpoint /general - confirmado
    # contra a documentação oficial (doc.yaml) da API.
    endpoint = '/cities' if detalhamento == 'municipio' else '/general'

    resp = request_com_retry('post', f'{COMEX_BASE}{endpoint}', json=payload, timeout=30)
    resp.raise_for_status()
    dados_brutos = resp.json()

    # A API retorna um objeto com os dados em 'data' -> 'list'. Confirmado em
    # produção (teste real com SC/exportações, 474 registros): o nome do
    # município vem no campo 'noMunMinsgUf', no formato "Nome do Município - UF"
    # (ex: "Palhoça - SC"), e não em 'city'/'coCity' como a documentação sugeria.
    lista = dados_brutos.get('data', {}).get('list', [])

    # Campos de agrupamento conhecidos por detalhamento (quando não é por
    # município). Mapeamento best-effort, baseado no padrão noXxx/noXxxEng
    # observado na API - não totalmente validado contra chamada real para
    # todo detalhamento, dado que exigiria N testes against a API externa;
    # se o campo não existir na resposta, cai no fallback 'rotulo' genérico.
    _CAMPO_ROTULO_POR_DETALHE = {
        'pais': 'noCountry',
        'uf': 'noState',
        'ncm': 'noNcmPortuguese',
        'bloco_economico': 'noBlock',
        'via_transporte': 'noViaTransport',
        'secao': 'noSection',
        'urf': 'noUrf',
    }

    resultado = []
    for item in lista:
        if detalhamento == 'municipio':
            nome_mun_uf = item.get('noMunMinsgUf')
            if nome_mun_uf:
                rotulo, _, sigla_uf = nome_mun_uf.rpartition(' - ')
            else:
                rotulo, sigla_uf = 'Desconhecido', None

            # Checagem defensiva: garante que o registro é mesmo de SC, já que
            # um código de UF incorreto no filtro causaria silenciosamente
            # dados de outro estado (como aconteceu antes com o código do
            # IBGE em vez do código próprio do Comex Stat). Se a UF vier e não
            # for SC, descarta.
            if sigla_uf and uf == UF_SC and sigla_uf != 'SC':
                continue
        else:
            campo_rotulo = _CAMPO_ROTULO_POR_DETALHE.get(detalhamento)
            rotulo = item.get(campo_rotulo) if campo_rotulo else None
            if rotulo is None:
                rotulo = 'Desconhecido'

        registro = {
            'rotulo': rotulo,
            'detalhamento': detalhamento,
            'fluxo': fluxo,
            'periodo': f'{ano_inicio}-{ano_fim}',
        }
        for chave_metrica in metricas:
            campo_api = METRICAS_DISPONIVEIS[chave_metrica]
            registro[chave_metrica] = item.get(campo_api)

        # Mantém as chaves antigas (municipio/valor_fob_usd/peso_liquido_kg)
        # quando o detalhamento é o padrão (município), para não quebrar o
        # restante do código (frontend, dataset export) que já depende delas.
        if detalhamento == 'municipio':
            registro['municipio'] = rotulo
            registro['valor_fob_usd'] = registro.get('fob')
            registro['peso_liquido_kg'] = registro.get('kg')

        resultado.append(registro)

    # Ordena pela primeira métrica pedida, decrescente — não garantido pela
    # API em si, mas é a ordem mais útil para quem consulta (maiores valores
    # primeiro) e o que a interface assume ao mostrar só os top N num gráfico.
    chave_ordenacao = metricas[0] if metricas else None
    if chave_ordenacao:
        resultado.sort(key=lambda r: r.get(chave_ordenacao) or 0, reverse=True)

    return resultado


def listar_municipios_disponiveis_sc():
    """
    Lista os municípios de SC com dados disponíveis no Comex Stat,
    usando o endpoint de filtros da própria API.
    """
    resp = request_com_retry('get', f'{COMEX_BASE}/cities/filters/city', params={'state': UF_SC}, timeout=20)
    resp.raise_for_status()
    return resp.json()
