"""
Fase 2: busca artigos do NYT, grava em NYT_OWNER.NYT_ARTICLE (Oracle) e manda o e-mail com CSV
para o Kevin — mesma entrega do teste.py, mas rodando no servidor.

  GET  /health   -> {"status": "ok"}
  POST /run      -> Authorization: Bearer <RUN_TOKEN>; opcional ?to=<e-mail> para um teste sem
                    mandar para o destinatário padrão.

Variáveis de ambiente:
  NYT_API_KEY, RUN_TOKEN, YAHOO_USER, YAHOO_APP_PASSWORD, EMAIL_TO (padrão kjcoogan@gmail.com),
  ORACLE_DB_USER, ORACLE_DSN, ORACLE_DB_PASSWORD, ORACLE_WALLET_PASSWORD, ORACLE_WALLET_BASE64
"""
import csv
import hmac
import os
import smtplib
import tempfile
import traceback
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from fastapi import FastAPI, Header, HTTPException

from db import insert_articles
from nyt_client import fetch_articles

app = FastAPI()

RUN_TOKEN = os.environ["RUN_TOKEN"]
YAHOO_USER = os.environ["YAHOO_USER"]
YAHOO_APP_PASSWORD = os.environ["YAHOO_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", "kjcoogan@gmail.com")

CSV_COLUMNS = ["headline", "snippet", "abstract", "published_date", "byline", "section", "url"]


def _save_csv(articles: list[dict], path: str) -> None:
    # Mesmo formato do pandas.to_csv(index=False, encoding="utf-8-sig") do teste.py.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_COLUMNS)
        for a in articles:
            w.writerow([a.get(c) if a.get(c) is not None else "" for c in CSV_COLUMNS])


def _send_email(qtd_artigos: int, csv_path: str, to: str) -> None:
    # Texto idêntico ao do teste.py (inclusive o "\T" original, para o e-mail do Kevin não mudar).
    corpo = f"The article load was completed successfully.\\Total collected: {qtd_artigos} articles."
    msg = MIMEMultipart()
    msg["Subject"] = "✅ NYT load completed successfully"
    msg["From"] = YAHOO_USER
    msg["To"] = to
    msg.attach(MIMEText(corpo, "plain"))
    with open(csv_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(csv_path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(csv_path)}"'
        msg.attach(part)
    with smtplib.SMTP_SSL("smtp.mail.yahoo.com", 465, timeout=60) as server:
        server.login(YAHOO_USER, YAHOO_APP_PASSWORD)
        server.send_message(msg)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run")
def run(authorization: str = Header(None), to: Optional[str] = None):
    if not hmac.compare_digest(authorization or "", f"Bearer {RUN_TOKEN}"):
        raise HTTPException(status_code=401, detail="unauthorized")

    destinatario = to or EMAIL_TO
    end_date = datetime.today().strftime("%Y%m%d")
    begin_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")

    artigos = fetch_articles(begin_date, end_date)
    if not artigos:
        return {"status": "empty", "fetched": 0}

    # Banco e e-mail são independentes: uma falha no Oracle não impede o e-mail do cliente
    # (e vice-versa), mas qualquer falha faz a resposta ser 502 para o n8n sinalizar.
    db_result, db_error = None, None
    try:
        db_result = insert_articles(artigos)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        db_error = f"{type(e).__name__}: {str(e)[:200]}"

    email_error = None
    csv_path = os.path.join(tempfile.gettempdir(), f"nyt_articles_{begin_date}_a_{end_date}.csv")
    try:
        _save_csv(artigos, csv_path)
        _send_email(len(artigos), csv_path, destinatario)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        email_error = f"{type(e).__name__}: {str(e)[:200]}"

    body = {
        "fetched": len(artigos),
        "database": db_result if db_error is None else {"error": db_error},
        "email": "enviado" if email_error is None else {"error": email_error},
        "email_to": destinatario,
    }
    if db_error or email_error:
        raise HTTPException(status_code=502, detail={"status": "partial", **body})
    return {"status": "success", **body}
