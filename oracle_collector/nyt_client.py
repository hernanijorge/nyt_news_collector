import os
import time
import random
import requests

API_KEY = os.environ["NYT_API_KEY"]
BASE_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
NUM_PAGES = int(os.environ.get("NUM_PAGES", "50"))
BASE_SLEEP = 1
MAX_RETRIES_429 = 5


def fetch_articles(begin_date: str, end_date: str) -> list[dict]:
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
            resp = requests.get(BASE_URL, params=params, timeout=30)
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
            print(f"Erro HTTP {status_code} na página {page}: {e}")
            break
        except requests.exceptions.RequestException as e:
            # timeout / falha de rede: não derruba o que já foi coletado
            print(f"Erro de rede na página {page}: {e}")
            break
        else:
            consecutive_429 = 0
            data = resp.json()
            docs = (data.get("response") or {}).get("docs") or []
            if not docs:
                break
            for doc in docs:
                todos_artigos.append({
                    "headline":       (doc.get("headline") or {}).get("main"),
                    "snippet":        doc.get("snippet"),
                    "abstract":       doc.get("abstract"),
                    "published_date": doc.get("pub_date"),
                    "byline":         (doc.get("byline") or {}).get("original"),
                    "section":        doc.get("section_name"),
                    "url":            doc.get("web_url"),
                })
            page += 1

    return todos_artigos
