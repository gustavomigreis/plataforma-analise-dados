from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import os
import json

from db import get_connection, adapt_query, init_db, USE_POSTGRES, last_insert_id
import ibge

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


# Garante que o banco existe tanto rodando com `python app.py`
# quanto rodando via gunicorn (produção), onde __main__ nunca executa.
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port)
