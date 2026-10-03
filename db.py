"""
Camada de banco de dados: usa PostgreSQL quando DATABASE_URL está definida
(produção, no Render) e SQLite localmente (desenvolvimento), sem precisar
mudar o resto do código da aplicação.
"""
import os
import sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Render às vezes fornece a URL com "postgres://"; psycopg2 exige "postgresql://"
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)


def get_connection():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    else:
        DATA_DIR = os.environ.get('DATA_DIR', '.')
        os.makedirs(DATA_DIR, exist_ok=True)
        db_path = os.path.join(DATA_DIR, 'dados.db')
        return sqlite3.connect(db_path)


def placeholder():
    """Retorna o marcador de parâmetro certo para a query (%s ou ?)."""
    return '%s' if USE_POSTGRES else '?'


def adapt_query(query):
    """Converte uma query escrita com '?' para '%s' quando usando Postgres."""
    if USE_POSTGRES:
        return query.replace('?', '%s')
    return query


def init_db():
    conn = get_connection()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute('''CREATE TABLE IF NOT EXISTS datasets
                     (id SERIAL PRIMARY KEY,
                      nome TEXT NOT NULL,
                      descricao TEXT,
                      criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      tipo TEXT,
                      colunas TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS dados
                     (id SERIAL PRIMARY KEY,
                      dataset_id INTEGER NOT NULL REFERENCES datasets(id),
                      dados_json TEXT NOT NULL)''')

        c.execute('''CREATE TABLE IF NOT EXISTS analises
                     (id SERIAL PRIMARY KEY,
                      dataset_id INTEGER NOT NULL REFERENCES datasets(id),
                      nome_analise TEXT NOT NULL,
                      tipo TEXT,
                      parametros TEXT,
                      resultado TEXT,
                      criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    else:
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


def last_insert_id(cursor, conn):
    """Obtém o ID do último INSERT, compatível com Postgres e SQLite."""
    if USE_POSTGRES:
        return cursor.fetchone()[0]
    return cursor.lastrowid
