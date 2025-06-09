
import requests
import mysql.connector 
import time
import random
import pandas as pd
from datetime import datetime, timedelta
import time

# === CONFIGURAÇÕES ===
API_KEY = "REMOVIDO"
BASE_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
#BEGIN_DATE = "20250501"
#END_DATE = "20250531"
# Data final é ontem
END_DATE = (datetime.today() - timedelta(days=1)).strftime('%Y%m%d')
# Data inicial é X dias antes do END_DATE, por exemplo, 7 dias atrás
BEGIN_DATE = (datetime.strptime(END_DATE, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
NUM_PAGES = 10
BASE_SLEEP = 1
MAX_RETRIES_429 = 5

# === BANCO DE DADOS (MySQL) ===
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'REMOVIDO',
    'database': 'nyt_db',
    'charset': 'utf8mb4'
}

def connect_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nyt_articles (
            web_url VARCHAR(512) PRIMARY KEY,
            headline TEXT,
            snippet TEXT,
            abstract TEXT,
            published_date DATETIME,
            byline TEXT,
            section VARCHAR(255)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')
    conn.commit()
    return conn

# === INSERIR NO BANCO ===
def insert_articles(conn, articles):
    cursor = conn.cursor()
    for art in articles:
        cursor.execute("""
            INSERT IGNORE INTO nyt_articles 
            (web_url, headline, snippet, abstract, published_date, byline, section)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            art["url"],
            art["headline"],
            art["snippet"],
            art["abstract"],
            art["published_date"],
            art["byline"],
            art["section"],
        ))
    conn.commit()

# === COLETA ===
def fetch_articles():
    todos_artigos = []
    page = 0
    consecutive_429 = 0

    while page < NUM_PAGES:
        params = {
            "api-key": API_KEY,
            "page": page,
            "begin_date": BEGIN_DATE,
            "end_date": END_DATE,
        }

        time.sleep(BASE_SLEEP + random.uniform(0, 0.5))

        try:
            resp = requests.get(BASE_URL, params=params)
            resp.raise_for_status()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None

            if status_code == 429:
                consecutive_429 += 1
                if consecutive_429 > MAX_RETRIES_429:
                    print(f"• Muitas tentativas 429. Interrompendo no page={page}.")
                    break
                wait_seconds = min(2 ** consecutive_429, 60)
                print(f"• HTTP 429 na página {page}. Aguardando {wait_seconds}s e tentando de novo...")
                time.sleep(wait_seconds)
                continue

            else:
                print(f"• Erro HTTP {status_code} na página {page}: {e}")
                break

        else:
            consecutive_429 = 0
            data = resp.json()
            docs = data.get("response", {}).get("docs", [])

            if not docs:
                print(f"→ Página {page} sem resultados. Interrompendo.")
                break

            for doc in docs:
                todos_artigos.append({
                    "headline":       doc.get("headline", {}).get("main"),
                    "snippet":        doc.get("snippet"),
                    "abstract":       doc.get("abstract"),
                    "published_date": doc.get("pub_date"),
                    "byline":         doc.get("byline", {}).get("original"),
                    "section":        doc.get("section_name"),
                    "url":            doc.get("web_url"),
                })

            print(f"→ Página {page} processada, acumulado: {len(todos_artigos)} artigos")
            page += 1

    return todos_artigos

# === MAIN ===
def main():
    print("Iniciando coleta de artigos...")
    conn = connect_db()
    artigos = fetch_articles()
    if artigos:
        insert_articles(conn, artigos)
        print(f"✅ Inseridos {len(artigos)} artigos no banco de dados.")
    else:
        print("⚠️ Nenhum artigo coletado.")
    conn.close()
    print("🌟 Finalizado.")

if __name__ == "__main__":
    main()

# === EXECUÇÃO DIÁRIA AUTOMÁTICA ===
while True:
    main()
    print("✅ Execução finalizada. Aguardando 20 minutos...")
    time.sleep(1200)  # Espera 20 minutos
