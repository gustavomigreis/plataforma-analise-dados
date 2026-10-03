from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sqlite3
import pandas as pd
import numpy as np
import os
from datetime import datetime
import json

app = Flask(__name__)
CORS(app)

# Em produção (Render), usa um disco persistente montado em /var/data se existir.
# Localmente, usa a pasta atual.
DATA_DIR = os.environ.get('DATA_DIR', '.')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'dados.db')
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS datasets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nome TEXT NOT NULL,
                  descricao TEXT,
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  tipo TEXT,
                  colunas TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS dados
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  dataset_id INTEGER NOT NULL,
                  dados_json TEXT NOT NULL,
                  FOREIGN KEY(dataset_id) REFERENCES datasets(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS analises
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  dataset_id INTEGER NOT NULL,
                  nome_analise TEXT NOT NULL,
                  tipo TEXT,
                  parametros TEXT,
                  resultado TEXT,
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(dataset_id) REFERENCES datasets(id))''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/datasets', methods=['GET'])
def listar_datasets():
    conn = sqlite3.connect(DB_PATH)
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
                'criado_em': d[3],
                'tipo': d[4]
            } for d in datasets
        ]
    })

@app.route('/api/datasets/<int:dataset_id>', methods=['GET'])
def obter_dataset(dataset_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT nome, descricao, tipo, colunas FROM datasets WHERE id = ?', (dataset_id,))
    dataset_info = c.fetchone()
    
    if not dataset_info:
        conn.close()
        return jsonify({'erro': 'Dataset não encontrado'}), 404
    
    c.execute('SELECT dados_json FROM dados WHERE dataset_id = ? LIMIT 1000', (dataset_id,))
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
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        colunas = ','.join(df.columns)
        c.execute('INSERT INTO datasets (nome, descricao, tipo, colunas) VALUES (?, ?, ?, ?)',
                  (nome_dataset, descricao, 'geográfico-econômico-social', colunas))
        dataset_id = c.lastrowid
        
        for _, row in df.iterrows():
            dados_json = json.dumps(row.to_dict())
            c.execute('INSERT INTO dados (dataset_id, dados_json) VALUES (?, ?)',
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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT dados_json FROM dados WHERE dataset_id = ?', (dataset_id,))
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
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO analises (dataset_id, nome_analise, tipo, resultado) VALUES (?, ?, ?, ?)',
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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT dados_json FROM dados WHERE dataset_id = ?', (dataset_id,))
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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT dados_json FROM dados WHERE dataset_id = ?', (dataset_id,))
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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT dados_json FROM dados WHERE dataset_id = ?', (dataset_id,))
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

# Garante que o banco existe tanto rodando com `python app.py`
# quanto rodando via gunicorn (produção), onde __main__ nunca executa.
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port)
