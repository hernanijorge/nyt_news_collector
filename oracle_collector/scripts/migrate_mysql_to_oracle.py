"""
Backfill único: MySQL local (nyt_articles) -> Oracle NYT_OWNER.NYT_ARTICLE.

Roda local, não no Easypanel. Idempotente: UNIQUE(ARTICLE_URL) faz linhas já
existentes virarem "duplicadas" em vez de duplicarem.

Uso (a partir de oracle_collector/):
  python scripts/migrate_mysql_to_oracle.py --dry-run     # só conta/converte, não grava
  python scripts/migrate_mysql_to_oracle.py --limit 1000  # teste com poucas linhas
  python scripts/migrate_mysql_to_oracle.py               # tudo
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mysql.connector
from db import get_connection, insert_articles

MYSQL_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "user": os.environ["MYSQL_USER"],
    "password": os.environ["MYSQL_PASSWORD"],
    "database": os.environ.get("MYSQL_DATABASE", "nyt_db"),
    "charset": "utf8mb4",
}

BATCH_SIZE = 500


def count_mysql_rows() -> int:
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM nyt_articles")
    (total,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return total


def fetch_mysql_batches(limit=None):
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor(dictionary=True)
    sql = "SELECT web_url, headline, snippet, abstract, published_date, byline, section FROM nyt_articles"
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql)
    while True:
        rows = cursor.fetchmany(BATCH_SIZE)
        if not rows:
            break
        yield rows
    cursor.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="não conecta no Oracle nem grava")
    parser.add_argument("--limit", type=int, help="migra só as N primeiras linhas")
    args = parser.parse_args()

    total_rows = count_mysql_rows()
    if args.limit:
        total_rows = min(total_rows, args.limit)
    print(f"Linhas a processar (MySQL nyt_articles): {total_rows}" + ("  [DRY-RUN]" if args.dry_run else ""))

    ora_conn = None if args.dry_run else get_connection()
    total_inserted = total_skipped = total_failed = processed = 0
    start = time.monotonic()

    try:
        for batch in fetch_mysql_batches(args.limit):
            articles = [
                {
                    "url": r["web_url"],
                    "headline": r["headline"],
                    "snippet": r["snippet"],
                    "abstract": r["abstract"],
                    "published_date": r["published_date"],
                    "byline": r["byline"],
                    "section": r["section"],
                }
                for r in batch
            ]
            if args.dry_run:
                result = {"inserted": 0, "skipped_duplicates": 0, "failed": 0}
            else:
                result = insert_articles(articles, conn=ora_conn)
                if result.get("error_samples"):
                    print("  ! erros:", result["error_samples"])
            total_inserted += result["inserted"]
            total_skipped += result["skipped_duplicates"]
            total_failed += result["failed"]
            processed += len(batch)

            elapsed = time.monotonic() - start
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total_rows - processed) / rate if rate > 0 else float("nan")
            print(
                f"[{processed}/{total_rows}] +{result['inserted']} inseridos, "
                f"+{result['skipped_duplicates']} duplicados, {result['failed']} falhas "
                f"| acumulado: {total_inserted} / {total_skipped} / {total_failed} "
                f"| {elapsed:6.1f}s | {rate:6.1f} linhas/s | ETA: {eta:6.1f}s"
            )
    finally:
        if ora_conn is not None:
            ora_conn.close()

    total_elapsed = time.monotonic() - start
    print(
        f"\nConcluído em {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min). "
        f"Inseridos: {total_inserted}. Duplicados: {total_skipped}. Falhas: {total_failed}. "
        f"Taxa média: {processed / max(total_elapsed, 1e-9):.1f} linhas/s."
    )


if __name__ == "__main__":
    main()
