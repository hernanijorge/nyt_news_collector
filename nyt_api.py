# app.py (nomeado nyt_api.py no projeto local)
import os
import time
import random
import smtplib
import tempfile
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

import requests
import mysql.connector
import pandas as pd
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()

API_KEY = os.environ["NYT_API_KEY"]
BASE_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
NUM_PAGES = int(os.environ.get("NUM_PAGES", "50"))
BASE_SLEEP = 1
MAX_RETRIES_429 = 5
RUN_TOKEN = os.environ["RUN_TOKEN"]  # token que só o n8n vai conhecer

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ.get("DB_NAME", "nyt_db"),
    "charset": "utf8mb4",
}

YAHOO_USER = os.environ["YAHOO_USER"]
YAHOO_APP_PASSWORD = os.environ["YAHOO_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", "hernani.jorge1@gmail.com")

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
            art["url"], art["headline"], art["snippet"], art["abstract"],
            art["published_date"], art["byline"], art["section"],
        ))
    conn.commit()

def fetch_articles(begin_date, end_date):
    todos_artigos = []
    page = 0
    consecutive_429 = 0

    while page < NUM_PAGES:
        params = {
            "api-key": API_KEY,
            "page": page,
            "begin_date": begin_date,
            "end_date": end_date,
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
                    print(f"Muitas tentativas 429. Interrompendo no page={page}.")
                    break
                wait_seconds = min(3 ** consecutive_429 * 6, 120)
                print(f"HTTP 429 na página {page}. Aguardando {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            else:
                print(f"Erro HTTP {status_code} na página {page}: {e}")
                break
        else:
            consecutive_429 = 0
            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                print(f"Página {page} sem resultados. Interrompendo.")
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
            page += 1

    return todos_artigos

def enviar_email_sucesso(qtd_artigos, caminho_csv):
    corpo = f"The article load was completed successfully.\nTotal collected: {qtd_artigos} articles."
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
    with smtplib.SMTP_SSL("smtp.mail.yahoo.com", 465) as server:
        server.login(YAHOO_USER, YAHOO_APP_PASSWORD)
        server.send_message(msg)

@app.post("/run")
def run(authorization: str = Header(None)):
    if authorization != f"Bearer {RUN_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")

    end_date = datetime.today().strftime("%Y%m%d")
    begin_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")

    conn = connect_db()
    artigos = fetch_articles(begin_date, end_date)
    if not artigos:
        conn.close()
        return {"status": "empty", "count": 0}

    insert_articles(conn, artigos)
    df = pd.DataFrame(artigos)
    ##filename = f"/tmp/nyt_articles_{begin_date}_a_{end_date}.csv"
    filename = os.path.join(tempfile.gettempdir(), f"nyt_articles_{begin_date}_a_{end_date}.csv")
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    enviar_email_sucesso(len(artigos), filename)
    conn.close()
    return {"status": "success", "count": len(artigos)}