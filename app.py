from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import json

from db import get_connection, adapt_query, init_db, USE_POSTGRES, last_insert_id
import ibge
import comexstat
import bcb
import objetos as objetos_mod

app = Flask(__name__)
CORS(app)

# Pasta de uploads temporários (não usada para persistência de dados,
# apenas como espaço de trabalho do Flask durante o processamento).
DATA_DIR = os.environ.get('DATA_DIR', '.')
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def q(query):
    """Atalho para adaptar a query ao dialeto do banco em uso."""
    return adapt_query(query)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/datasets', methods=['GET'])
def listar_datasets():
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, nome, descricao, criado_em, tipo FROM datasets ORDER BY criado_em DESC')
    datasets = c.fetchall()
    conn.close()

    return jsonify({
        'datasets': [
            {
                'id': d[0],
                'nome': d[1],
                'descricao': d[2],
                'criado_em': str(d[3]),
                'tipo': d[4]
            } for d in datasets
        ]
    })


@app.route('/api/datasets/<int:dataset_id>', methods=['GET'])
def obter_dataset(dataset_id):
    conn = get_connection()
    c = conn.cursor()

    c.execute(q('SELECT nome, descricao, tipo, colunas FROM datasets WHERE id = ?'), (dataset_id,))
    dataset_info = c.fetchone()

    if not dataset_info:
        conn.close()
        return jsonify({'erro': 'Dataset não encontrado'}), 404

    c.execute(q('SELECT dados_json FROM dados WHERE dataset_id = ? LIMIT 1000'), (dataset_id,))
    rows = c.fetchall()
    conn.close()

    dados = [json.loads(row[0]) for row in rows]

    return jsonify({
        'nome': dataset_info[0],
        'descricao': dataset_info[1],
        'tipo': dataset_info[2],
        'colunas': dataset_info[3].split(',') if dataset_info[3] else [],
        'dados': dados
    })


@app.route('/api/upload', methods=['POST'])
def upload_dados():
    if 'file' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo fornecido'}), 400

    file = request.files['file']
    nome_dataset = request.form.get('nome', file.filename)
    descricao = request.form.get('descricao', '')

    if file.filename == '':
        return jsonify({'erro': 'Arquivo não selecionado'}), 400

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            return jsonify({'erro': 'Formato não suportado. Use CSV ou Excel'}), 400

        conn = get_connection()
        c = conn.cursor()

        colunas = ','.join(df.columns)

        if USE_POSTGRES:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (%s, %s, %s, %s) RETURNING id',
                (nome_dataset, descricao, 'geográfico-econômico-social', colunas)
            )
        else:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                (nome_dataset, descricao, 'geográfico-econômico-social', colunas)
            )
        dataset_id = last_insert_id(c, conn)

        for _, row in df.iterrows():
            dados_json = json.dumps(row.to_dict(), default=str)
            c.execute(q('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)'),
                      (dataset_id, dados_json))

        conn.commit()
        conn.close()

        return jsonify({
            'sucesso': True,
            'dataset_id': dataset_id,
            'nome': nome_dataset,
            'linhas': len(df),
            'colunas': list(df.columns)
        })

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/analise/estatistica', methods=['POST'])
def analise_estatistica():
    data = request.json
    dataset_id = data.get('dataset_id')
    coluna = data.get('coluna')

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(q('SELECT dados_json FROM dados WHERE dataset_id = ?'), (dataset_id,))
        rows = c.fetchall()

        valores = []
        for row in rows:
            dado = json.loads(row[0])
            if coluna in dado:
                try:
                    valores.append(float(dado[coluna]))
                except (ValueError, TypeError):
                    pass

        if not valores:
            conn.close()
            return jsonify({'erro': 'Nenhum valor numérico encontrado'}), 400

        valores_arr = np.array(valores)

        resultado = {
            'coluna': coluna,
            'contagem': len(valores),
            'media': float(np.mean(valores_arr)),
            'mediana': float(np.median(valores_arr)),
            'desvio_padrao': float(np.std(valores_arr)),
            'variancia': float(np.var(valores_arr)),
            'minimo': float(np.min(valores_arr)),
            'maximo': float(np.max(valores_arr)),
            'q1': float(np.percentile(valores_arr, 25)),
            'q3': float(np.percentile(valores_arr, 75))
        }

        c.execute(q('INSERT INTO analises (dataset_id, nome_analise, tipo, resultado) VALUES (?, ?, ?, ?)'),
                  (dataset_id, f'Estatística - {coluna}', 'estatística', json.dumps(resultado)))
        conn.commit()
        conn.close()

        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/analise/correlacao', methods=['POST'])
def analise_correlacao():
    data = request.json
    dataset_id = data.get('dataset_id')

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(q('SELECT dados_json FROM dados WHERE dataset_id = ?'), (dataset_id,))
        rows = c.fetchall()
        conn.close()

        dados = [json.loads(row[0]) for row in rows]
        df = pd.DataFrame(dados)

        df_numericas = df.select_dtypes(include=[np.number])

        if df_numericas.empty:
            return jsonify({'erro': 'Nenhuma coluna numérica encontrada'}), 400

        correlacao = df_numericas.corr().to_dict()

        return jsonify({'correlacao': correlacao})

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/analise/distribuicao', methods=['POST'])
def analise_distribuicao():
    data = request.json
    dataset_id = data.get('dataset_id')
    coluna = data.get('coluna')
    bins = data.get('bins', 10)

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(q('SELECT dados_json FROM dados WHERE dataset_id = ?'), (dataset_id,))
        rows = c.fetchall()
        conn.close()

        valores = []
        for row in rows:
            dado = json.loads(row[0])
            if coluna in dado:
                try:
                    valores.append(float(dado[coluna]))
                except (ValueError, TypeError):
                    pass

        if not valores:
            return jsonify({'erro': 'Nenhum valor numérico encontrado'}), 400

        contagens, limites = np.histogram(valores, bins=bins)

        resultado = {
            'coluna': coluna,
            'contagens': contagens.tolist(),
            'limites': limites.tolist(),
            'bins': bins
        }

        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/analise/agrupamento', methods=['POST'])
def analise_agrupamento():
    data = request.json
    dataset_id = data.get('dataset_id')
    coluna_grupo = data.get('coluna_grupo')
    coluna_valor = data.get('coluna_valor')
    funcao = data.get('funcao', 'mean')

    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(q('SELECT dados_json FROM dados WHERE dataset_id = ?'), (dataset_id,))
        rows = c.fetchall()
        conn.close()

        dados = [json.loads(row[0]) for row in rows]
        df = pd.DataFrame(dados)

        if coluna_grupo not in df.columns or coluna_valor not in df.columns:
            return jsonify({'erro': 'Colunas não encontradas'}), 400

        agrupado = df.groupby(coluna_grupo)[coluna_valor].agg(funcao)

        resultado = {
            'grupos': agrupado.index.tolist(),
            'valores': agrupado.values.tolist(),
            'funcao': funcao
        }

        return jsonify(resultado)

    except Exception as e:
        return jsonify({'erro': str(e)}), 500


@app.route('/api/ibge/indicadores', methods=['GET'])
def ibge_indicadores():
    """Lista os indicadores do IBGE disponíveis para consulta."""
    return jsonify({
        'indicadores': [
            {'chave': k, 'nome': v['nome'], 'unidade': v['unidade']}
            for k, v in ibge.INDICADORES.items()
        ]
    })


@app.route('/api/ibge/municipios', methods=['GET'])
def ibge_municipios():
    """Lista os municípios de Santa Catarina com seus códigos IBGE."""
    try:
        municipios = ibge.buscar_municipios_sc()
        return jsonify({'municipios': municipios})
    except Exception as e:
        return jsonify({'erro': f'Falha ao consultar IBGE: {str(e)}'}), 502


@app.route('/api/ibge/perfil/<int:codigo_municipio>', methods=['GET'])
def ibge_perfil_municipio(codigo_municipio):
    """
    Retorna um "Perfil do Município" completo (estilo IBGE Cidades):
    população, área, densidade, PIB, PIB per capita, rendimento e alfabetização,
    tudo em uma única consulta.
    """
    try:
        perfil = ibge.buscar_perfil_municipio(codigo_municipio)
        return jsonify({'perfil': perfil})
    except Exception as e:
        return jsonify({'erro': f'Falha ao consultar perfil no IBGE: {str(e)}'}), 502


@app.route('/api/ibge/perfil/<int:codigo_municipio>/salvar', methods=['POST'])
def ibge_perfil_salvar(codigo_municipio):
    """Salva o perfil completo do município como um dataset na plataforma."""
    data = request.json or {}
    nome_municipio = data.get('nome_municipio', f'Município {codigo_municipio}')
    nome_dataset = data.get('nome') or f'IBGE - Perfil de {nome_municipio}'

    try:
        perfil = ibge.buscar_perfil_municipio(codigo_municipio)

        registro = {'municipio': nome_municipio, 'codigo_ibge': codigo_municipio}
        for chave, info in perfil.items():
            registro[info['nome']] = info['valor']

        conn = get_connection()
        c = conn.cursor()
        colunas = ','.join(registro.keys())

        if USE_POSTGRES:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (%s, %s, %s, %s) RETURNING id',
                (nome_dataset, 'Perfil municipal importado da API do IBGE/SIDRA', 'ibge', colunas)
            )
        else:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                (nome_dataset, 'Perfil municipal importado da API do IBGE/SIDRA', 'ibge', colunas)
            )
        dataset_id = last_insert_id(c, conn)

        c.execute(q('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)'),
                  (dataset_id, json.dumps(registro, default=str)))

        conn.commit()
        conn.close()

        return jsonify({'sucesso': True, 'dataset_id': dataset_id, 'nome': nome_dataset, 'linhas': 1})

    except Exception as e:
        return jsonify({'erro': f'Falha ao salvar perfil: {str(e)}'}), 502


@app.route('/api/ibge/consultar', methods=['POST'])
def ibge_consultar():
    """
    Consulta um indicador do IBGE/SIDRA e retorna os dados brutos
    (sem salvar), para o usuário pré-visualizar antes de importar.
    """
    data = request.json
    indicador = data.get('indicador')
    nivel = data.get('nivel')
    codigo_localidade = data.get('codigo_localidade')
    periodo = data.get('periodo', 'last')

    try:
        resultado = ibge.buscar_dados(indicador, nivel, codigo_localidade, periodo)
        return jsonify({'dados': resultado, 'total': len(resultado)})
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao consultar IBGE: {str(e)}'}), 502


@app.route('/api/ibge/importar', methods=['POST'])
def ibge_importar():
    """
    Consulta um indicador do IBGE/SIDRA e salva o resultado como um novo
    dataset na plataforma, pronto para usar nas ferramentas de análise.
    """
    data = request.json
    indicador = data.get('indicador')
    nivel = data.get('nivel')
    codigo_localidade = data.get('codigo_localidade')
    periodo = data.get('periodo', 'last')
    nome_dataset = data.get('nome')

    try:
        registros = ibge.buscar_dados(indicador, nivel, codigo_localidade, periodo)

        if not registros:
            return jsonify({'erro': 'Nenhum dado retornado pelo IBGE para esses parâmetros'}), 400

        if not nome_dataset:
            nome_ind = ibge.INDICADORES[indicador]['nome']
            nome_dataset = f'IBGE - {nome_ind} ({nivel})'

        conn = get_connection()
        c = conn.cursor()

        colunas = ','.join(registros[0].keys())

        if USE_POSTGRES:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (%s, %s, %s, %s) RETURNING id',
                (nome_dataset, 'Importado da API do IBGE/SIDRA', 'ibge', colunas)
            )
        else:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                (nome_dataset, 'Importado da API do IBGE/SIDRA', 'ibge', colunas)
            )
        dataset_id = last_insert_id(c, conn)

        for registro in registros:
            dados_json = json.dumps(registro, default=str)
            c.execute(q('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)'),
                      (dataset_id, dados_json))

        conn.commit()
        conn.close()

        return jsonify({
            'sucesso': True,
            'dataset_id': dataset_id,
            'nome': nome_dataset,
            'linhas': len(registros)
        })

    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao importar dados do IBGE: {str(e)}'}), 502


@app.route('/api/comex/consultar', methods=['POST'])
def comex_consultar():
    """
    Consulta a API do Comex Stat (MDIC) para exportações/importações por
    município de Santa Catarina.
    """
    data = request.json or {}
    fluxo = data.get('fluxo')
    ano_inicio = data.get('ano_inicio')
    ano_fim = data.get('ano_fim')
    codigo_municipio = data.get('codigo_municipio')

    try:
        resultado = comexstat.buscar_comercio_exterior(
            fluxo, ano_inicio, ano_fim, codigo_municipio
        )
        return jsonify({'dados': resultado, 'total': len(resultado)})
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao consultar Comex Stat: {str(e)}'}), 502


@app.route('/api/comex/importar', methods=['POST'])
def comex_importar():
    """Consulta o Comex Stat e salva o resultado como um dataset na plataforma."""
    data = request.json or {}
    fluxo = data.get('fluxo')
    ano_inicio = data.get('ano_inicio')
    ano_fim = data.get('ano_fim')
    codigo_municipio = data.get('codigo_municipio')
    nome_dataset = data.get('nome')

    try:
        registros = comexstat.buscar_comercio_exterior(
            fluxo, ano_inicio, ano_fim, codigo_municipio
        )

        if not registros:
            return jsonify({'erro': 'Nenhum dado retornado pelo Comex Stat para esses parâmetros'}), 400

        if not nome_dataset:
            nome_fluxo = 'Exportações' if fluxo == 'exportacao' else 'Importações'
            nome_dataset = f'Comex Stat - {nome_fluxo} SC ({ano_inicio}-{ano_fim})'

        conn = get_connection()
        c = conn.cursor()
        colunas = ','.join(registros[0].keys())

        if USE_POSTGRES:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (%s, %s, %s, %s) RETURNING id',
                (nome_dataset, 'Importado da API do Comex Stat (MDIC)', 'comex', colunas)
            )
        else:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                (nome_dataset, 'Importado da API do Comex Stat (MDIC)', 'comex', colunas)
            )
        dataset_id = last_insert_id(c, conn)

        for registro in registros:
            c.execute(q('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)'),
                      (dataset_id, json.dumps(registro, default=str)))

        conn.commit()
        conn.close()

        return jsonify({'sucesso': True, 'dataset_id': dataset_id, 'nome': nome_dataset, 'linhas': len(registros)})

    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao importar dados do Comex Stat: {str(e)}'}), 502


@app.route('/api/bcb/indicadores', methods=['GET'])
def bcb_indicadores():
    """Lista os indicadores macroeconômicos disponíveis via BCB/SGS."""
    indicadores = [
        {'chave': chave, 'nome': info['nome'], 'unidade': info['unidade'], 'frequencia': info['frequencia']}
        for chave, info in bcb.INDICADORES.items()
    ]
    return jsonify({'indicadores': indicadores})


@app.route('/api/bcb/consultar', methods=['POST'])
def bcb_consultar():
    """
    Consulta a API SGS do Banco Central para um indicador macro
    (Selic, IPCA, câmbio, dívida pública).
    """
    data = request.json or {}
    indicador = data.get('indicador')
    data_inicial = data.get('data_inicial')
    data_final = data.get('data_final')

    try:
        quantidade = int(data.get('quantidade', 24))
    except (TypeError, ValueError):
        return jsonify({'erro': 'Quantidade inválida: deve ser um número inteiro'}), 400

    try:
        resultado = bcb.buscar_serie(indicador, quantidade=quantidade,
                                      data_inicial=data_inicial, data_final=data_final)
        return jsonify({'dados': resultado, 'total': len(resultado)})
    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao consultar o Banco Central (BCB/SGS): {str(e)}'}), 502


@app.route('/api/bcb/importar', methods=['POST'])
def bcb_importar():
    """Consulta o BCB/SGS e salva o resultado como um dataset na plataforma."""
    data = request.json or {}
    indicador = data.get('indicador')
    data_inicial = data.get('data_inicial')
    data_final = data.get('data_final')
    nome_dataset = data.get('nome')

    try:
        quantidade = int(data.get('quantidade', 24))
    except (TypeError, ValueError):
        return jsonify({'erro': 'Quantidade inválida: deve ser um número inteiro'}), 400

    try:
        registros = bcb.buscar_serie(indicador, quantidade=quantidade,
                                      data_inicial=data_inicial, data_final=data_final)

        if not registros:
            return jsonify({'erro': 'Nenhum dado retornado pelo BCB para esses parâmetros'}), 400

        if not nome_dataset:
            nome_indicador = bcb.INDICADORES.get(indicador, {}).get('nome', indicador)
            nome_dataset = f'BCB - {nome_indicador}'

        conn = get_connection()
        c = conn.cursor()
        colunas = ','.join(registros[0].keys())

        if USE_POSTGRES:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (%s, %s, %s, %s) RETURNING id',
                (nome_dataset, 'Importado da API SGS do Banco Central (BCB)', 'bcb', colunas)
            )
        else:
            c.execute(
                'INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                (nome_dataset, 'Importado da API SGS do Banco Central (BCB)', 'bcb', colunas)
            )
        dataset_id = last_insert_id(c, conn)

        for registro in registros:
            c.execute(q('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)'),
                      (dataset_id, json.dumps(registro, default=str)))

        conn.commit()
        conn.close()

        return jsonify({'sucesso': True, 'dataset_id': dataset_id, 'nome': nome_dataset, 'linhas': len(registros)})

    except ValueError as e:
        return jsonify({'erro': str(e)}), 400
    except Exception as e:
        return jsonify({'erro': f'Falha ao importar dados do BCB: {str(e)}'}), 502


@app.route('/api/objetos', methods=['GET'])
def listar_objetos():
    """
    Lista o catálogo unificado de objetos (indicadores) disponíveis nas três
    fontes de dados (IBGE/SIDRA, BCB, Comex Stat), opcionalmente filtrado por
    escala territorial (?escala=municipio, por exemplo).
    """
    escala = request.args.get('escala')
    try:
        return jsonify({'objetos': objetos_mod.listar_objetos(escala), 'escalas': objetos_mod.ESCALAS})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500


def _rodar_analises_automaticas(df_largo):
    """
    Dado um DataFrame "largo" (uma coluna por objeto selecionado, uma linha
    por localidade), roda as mesmas análises estatísticas já disponíveis na
    plataforma (estatística descritiva, correlação, distribuição,
    agrupamento) automaticamente sobre as colunas numéricas, para alimentar
    a tela de Pesquisa quando o usuário seleciona 2+ objetos.
    """
    resultado = {}
    colunas_numericas = df_largo.select_dtypes(include=[np.number]).columns.tolist()

    # Estatística descritiva por objeto (reaproveita a mesma lógica de
    # /api/analise/estatistica, mas em memória, sem passar por dataset salvo)
    descritivas = {}
    for col in colunas_numericas:
        valores = df_largo[col].dropna()
        if valores.empty:
            continue
        descritivas[col] = {
            'contagem': int(valores.count()),
            'media': float(valores.mean()),
            'mediana': float(valores.median()),
            'desvio_padrao': float(valores.std()) if valores.count() > 1 else 0.0,
            'minimo': float(valores.min()),
            'maximo': float(valores.max()),
        }
    resultado['estatisticas'] = descritivas

    # Correlação entre os objetos selecionados (só faz sentido com 2+ colunas
    # numéricas e com alguma variação nos dados)
    if len(colunas_numericas) >= 2:
        try:
            resultado['correlacao'] = df_largo[colunas_numericas].corr().round(4).to_dict()
        except Exception:
            resultado['correlacao'] = None
    else:
        resultado['correlacao'] = None

    # Distribuição (histograma) de cada objeto numérico
    distribuicoes = {}
    for col in colunas_numericas:
        valores = df_largo[col].dropna().values
        if len(valores) < 2:
            continue
        try:
            contagens, limites = np.histogram(valores, bins=min(10, len(valores)))
            distribuicoes[col] = {'contagens': contagens.tolist(), 'limites': limites.tolist()}
        except Exception:
            pass
    resultado['distribuicao'] = distribuicoes

    # Agrupamento (clustering) simples por quartil do primeiro objeto numérico,
    # como uma primeira visão de agrupamento das localidades sem exigir que o
    # usuário escolha parâmetros - uma clusterização k-means ficaria mais
    # pesada para o volume de dados típico desta tela (dezenas de municípios).
    if colunas_numericas:
        coluna_base = colunas_numericas[0]
        try:
            quartis = pd.qcut(df_largo[coluna_base], q=4, labels=['Q1 (menor)', 'Q2', 'Q3', 'Q4 (maior)'], duplicates='drop')
            agrupamento = {}
            for grupo, sub in df_largo.groupby(quartis, observed=True):
                agrupamento[str(grupo)] = sub['localidade'].tolist()
            resultado['agrupamento'] = {'coluna_base': coluna_base, 'grupos': agrupamento}
        except Exception:
            resultado['agrupamento'] = None
    else:
        resultado['agrupamento'] = None

    return resultado


@app.route('/api/pesquisa/consultar', methods=['POST'])
def pesquisa_consultar():
    """
    Endpoint da tela de Pesquisa: recebe uma escala territorial e uma lista
    de objetos (indicadores de qualquer uma das três fontes) e devolve os
    dados de cada um já organizados por localidade. Quando 2 ou mais objetos
    são selecionados, roda automaticamente as análises estatísticas
    (descritiva, correlação, distribuição, agrupamento) sobre a seleção.
    """
    data = request.json or {}
    escala = data.get('escala')
    chaves_objetos = data.get('objetos', [])
    codigo_localidade = data.get('codigo_localidade')
    periodo = data.get('periodo', 'last')
    ano_inicio = data.get('ano_inicio')
    ano_fim = data.get('ano_fim')

    if not escala or escala not in objetos_mod.ESCALAS:
        return jsonify({'erro': f'Escala inválida. Opções: {", ".join(objetos_mod.ESCALAS)}'}), 400
    if not chaves_objetos:
        return jsonify({'erro': 'Selecione ao menos um objeto para pesquisar'}), 400

    resultados_por_objeto = []
    erros = []
    for chave in chaves_objetos:
        try:
            r = objetos_mod.buscar_serie_objeto(
                chave, escala, codigo_localidade=codigo_localidade, periodo=periodo,
                ano_inicio=ano_inicio, ano_fim=ano_fim
            )
            resultados_por_objeto.append(r)
        except ValueError as e:
            erros.append({'objeto': chave, 'erro': str(e)})
        except Exception as e:
            erros.append({'objeto': chave, 'erro': f'Falha ao consultar: {str(e)}'})

    resposta = {'escala': escala, 'resultados': resultados_por_objeto, 'erros': erros}

    # Análises automáticas: só fazem sentido com 2+ objetos que de fato
    # retornaram dado, e exigem reconciliar as séries por localidade comum
    # (ex: cruzar população x PIB por município só funciona se as duas
    # séries tiverem as mesmas localidades).
    objetos_com_dado = [r for r in resultados_por_objeto if r['serie']]
    if len(objetos_com_dado) >= 2:
        try:
            df_largo = None
            for r in objetos_com_dado:
                df_obj = pd.DataFrame(r['serie'])[['localidade', 'valor']].rename(columns={'valor': r['objeto']})
                df_largo = df_obj if df_largo is None else df_largo.merge(df_obj, on='localidade', how='outer')

            resposta['analises'] = _rodar_analises_automaticas(df_largo)
        except Exception as e:
            resposta['analises'] = {'erro': f'Falha ao rodar análises automáticas: {str(e)}'}

    return jsonify(resposta)


# Garante que o banco existe tanto rodando com `python app.py`
# quanto rodando via gunicorn (produção), onde __main__ nunca executa.
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port)
