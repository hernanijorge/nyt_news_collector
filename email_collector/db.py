#!/usr/bin/env python3
"""
Conexão com a Autonomous Database do OCI (google-alerts-db) e gravação em
NYT_OWNER.NYT_ARTICLE.

Mesmo padrão do db.py do google-alerts-parser: o wallet não vai na imagem nem
no repositório — chega via ORACLE_WALLET_BASE64 (conteúdo do .zip em Base64) e
é extraído em disco na primeira conexão.

Variáveis de ambiente (mesmos nomes usados no google-alerts-parser):
  ORACLE_WALLET_BASE64   -> Wallet_*.zip em Base64 (container / Easypanel)
  ORACLE_WALLET_PASSWORD -> senha definida no download do wallet
  ORACLE_DSN             -> connection string completa (serviço "_tp")
  ORACLE_DB_USER         -> default "NYT_OWNER"
  ORACLE_DB_PASSWORD     -> senha do NYT_OWNER
  ORACLE_WALLET_DIR      -> opcional; default /app/wallet. Em execução local,
                            aponte para uma pasta com o wallet já extraído e
                            ORACLE_WALLET_BASE64 deixa de ser necessário.

Tabela: NYT_OWNER.NYT_ARTICLE, dedup via UNIQUE(ARTICLE_URL).
"""
import base64
import io
import os
import zipfile
from datetime import datetime, timezone
from typing import Optional

import oracledb

WALLET_DIR = os.environ.get("ORACLE_WALLET_DIR", "/app/wallet")

INSERT_SQL = """
    INSERT INTO NYT_OWNER.NYT_ARTICLE
        (ARTICLE_URL, HEADLINE, SNIPPET, ABSTRACT, PUBLISHED_DATE, BYLINE, SECTION_NAME)
    VALUES
        (:url, :headline, :snippet, :abstract,
         FROM_TZ(CAST(:published_date AS TIMESTAMP), 'UTC'),
         :byline, :section_name)
"""

ORA_UNIQUE_VIOLATION = 1


def _ensure_wallet_extracted() -> None:
    if os.path.isdir(WALLET_DIR) and os.listdir(WALLET_DIR):
        return

    wallet_b64 = os.environ.get("ORACLE_WALLET_BASE64")
    if not wallet_b64:
        raise RuntimeError(
            "Wallet não encontrado: configure ORACLE_WALLET_BASE64 ou aponte "
            "ORACLE_WALLET_DIR para uma pasta com o wallet extraído."
        )

    os.makedirs(WALLET_DIR, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(wallet_b64))) as zf:
        zf.extractall(WALLET_DIR)


def get_connection() -> oracledb.Connection:
    _ensure_wallet_extracted()

    return oracledb.connect(
        user=os.environ.get("ORACLE_DB_USER", "NYT_OWNER"),
        password=os.environ["ORACLE_DB_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
        config_dir=WALLET_DIR,
        wallet_location=WALLET_DIR,
        wallet_password=os.environ["ORACLE_WALLET_PASSWORD"],
    )


def _trunc(value: Optional[str], max_bytes: int) -> Optional[str]:
    """Trunca por bytes UTF-8 (VARCHAR2 usa semântica BYTE) e devolve None se vazio."""
    if not value:
        return None
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def _to_naive_utc(value) -> Optional[datetime]:
    """
    Aceita string ISO da API do NYT ("2025-01-01T12:00:00+0000") ou datetime
    (MySQL, naive). Devolve datetime naive em UTC; o SQL aplica FROM_TZ(..., 'UTC').
    Formato irreconhecível vira NULL — não derruba o lote.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def insert_articles(articles: list[dict], conn: Optional[oracledb.Connection] = None) -> dict:
    """
    Insere em lote (executemany + batcherrors): linhas duplicadas (ORA-00001 em
    UQ_NYT_ARTICLE_URL) são ignoradas individualmente, sem desfazer as demais.
    Passe `conn` para reaproveitar uma conexão (backfill); senão abre e fecha uma.

    Retorno: inserted, skipped_duplicates, failed (linhas rejeitadas por outro
    motivo, ex.: URL inválida/longa demais) e, se houver, error_samples.
    """
    rows = []
    invalid = 0
    for art in articles:
        url = art.get("url")
        if not url or len(url.encode("utf-8")) > 1000:
            invalid += 1
            continue
        rows.append({
            "url": url,
            "headline": _trunc(art.get("headline"), 1000),
            "snippet": _trunc(art.get("snippet"), 4000),
            "abstract": _trunc(art.get("abstract"), 4000),
            "published_date": _to_naive_utc(art.get("published_date")),
            "byline": _trunc(art.get("byline"), 500),
            "section_name": _trunc(art.get("section"), 200),
        })

    result = {"inserted": 0, "skipped_duplicates": 0, "failed": invalid}
    if not rows:
        return result

    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.cursor()
        cur.setinputsizes(
            url=1000, headline=1000, snippet=4000, abstract=4000,
            published_date=oracledb.DB_TYPE_TIMESTAMP,
            byline=500, section_name=200,
        )
        cur.executemany(INSERT_SQL, rows, batcherrors=True)
        errors = cur.getbatcherrors()
        conn.commit()
    finally:
        if own_conn:
            conn.close()

    duplicates = sum(1 for e in errors if e.code == ORA_UNIQUE_VIOLATION)
    others = [e for e in errors if e.code != ORA_UNIQUE_VIOLATION]
    result["inserted"] = len(rows) - len(errors)
    result["skipped_duplicates"] = duplicates
    result["failed"] += len(others)
    if others:
        result["error_samples"] = [e.message for e in others[:3]]
    return result
