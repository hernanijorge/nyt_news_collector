import hmac
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Header, HTTPException

from nyt_client import fetch_articles
from db import insert_articles

app = FastAPI()
API_TOKEN = os.environ["NYT_COLLECTOR_API_TOKEN"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest-daily")
def ingest_daily(authorization: str = Header(None)):
    if not hmac.compare_digest(authorization or "", f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=401, detail="unauthorized")

    end_date = datetime.today().strftime("%Y%m%d")
    begin_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")

    articles = fetch_articles(begin_date, end_date)
    if not articles:
        return {"status": "empty", "fetched": 0, "inserted": 0, "skipped_duplicates": 0}

    result = insert_articles(articles)
    status = "partial" if result["failed"] else "success"
    return {"status": status, "fetched": len(articles), **result}
