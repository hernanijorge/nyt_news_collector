import os


def _load_env():
    """Lê KEY=VALUE de .env (na pasta deste arquivo). Variáveis já definidas no ambiente têm prioridade."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

import requests
import mysql.connector 
import time
import random
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import os

# === CONFIGURAÇÕES ===
API_KEY = os.environ["NYT_API_KEY_EMAIL"]
BASE_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
YAHOO_USER = os.environ.get("YAHOO_USER", "hernani_jorge@yahoo.com.br")
EMAIL_TO = os.environ.get("EMAIL_TO", "kjcoogan@gmail.com")
#BEGIN_DATE = "20250809"
#END_DATE = "20250810"
# Data final é ontem
#END_DATE = (datetime.today() - timedelta(days=1)).strftime('%Y%m%d')
END_DATE = datetime.today().strftime('%Y%m%d') 
# Data inicial é X dias antes do END_DATE, por exemplo, 1 dia atrás
BEGIN_DATE = (datetime.strptime(END_DATE, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
NUM_PAGES = 50
BASE_SLEEP = 1
MAX_RETRIES_429 = 5

print(f"🔎 Coletando de {BEGIN_DATE} até {END_DATE}")

# === BANCO DE DADOS (MySQL) ===
DB_CONFIG = {
    'host': os.environ.get("MYSQL_HOST", "localhost"),
    'user': os.environ["MYSQL_USER"],
    'password': os.environ["MYSQL_PASSWORD"],
    'database': os.environ.get("MYSQL_DATABASE", "nyt_db"),
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
                wait_seconds = min(3 ** consecutive_429 * 6, 120)
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

def enviar_email_sucesso(qtd_artigos, caminho_csv):
    corpo = f"The article load was completed successfully.\Total collected: {qtd_artigos} articles."

    msg = MIMEMultipart()
    msg["Subject"] = "✅ NYT load completed successfully"
    msg["From"] = YAHOO_USER
    msg["To"] = EMAIL_TO

    msg.attach(MIMEText(corpo, "plain"))

    if os.path.exists(caminho_csv):
        with open(caminho_csv, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(caminho_csv))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(caminho_csv)}"'
            msg.attach(part)
    else:
        print("⚠️ CSV não encontrado. E-mail será enviado sem anexo.")

    try:
        with smtplib.SMTP_SSL("smtp.mail.yahoo.com", 465) as server:
            server.login(YAHOO_USER, os.environ["YAHOO_APP_PASSWORD"])
            server.send_message(msg)
        print("📧 E-mail com anexo enviado.")
    except Exception as e:
        print(f"❌ Falha ao enviar e-mail: {e}")

# === MAIN ===
def main():
    print("Iniciando coleta de artigos...")
    conn = connect_db()
    artigos = fetch_articles()
    if artigos:
        insert_articles(conn, artigos)

        # Exportar para CSV
        df = pd.DataFrame(artigos)
        filename = f"nyt_articles_{BEGIN_DATE}_a_{END_DATE}.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"📁 CSV salvo: {filename}")

        enviar_email_sucesso(len(artigos), filename)
        print(f"✅ Inseridos {len(artigos)} artigos no banco de dados.")
    else:
        print("⚠️ Nenhum artigo coletado.")
    conn.close()
    print("🌟 Finalizado.")

if __name__ == "__main__":
    main()



