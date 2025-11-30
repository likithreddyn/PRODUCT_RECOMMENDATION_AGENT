# SerpAPI search module
# src/serp_search.py
"""
SerpAPI helper for product discovery.
- Uses SERPAPI_KEY from environment (.env).
- Returns a list of product URLs (organic results).
- Caches recent queries to data/pages/urls_cache.json
"""

import os
import time
import json
from pathlib import Path
from typing import List
from dotenv import load_dotenv
import requests

load_dotenv()  # loads .env into environment

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
if not SERPAPI_KEY:
    raise RuntimeError("SERPAPI_KEY not found. Add it to your .env file.")

# Basic config
SERPAPI_ENDPOINT = "https://serpapi.com/search"
CACHE_PATH = Path("../data/pages/urls_cache.json")  # relative to src/
RATE_LIMIT_SEC = 1.0  # polite delay between calls


def _ensure_cache():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE_PATH.exists():
        CACHE_PATH.write_text(json.dumps({}), encoding="utf-8")


def load_cache() -> dict:
    _ensure_cache()
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_cache(cache: dict):
    _ensure_cache()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def serp_search(query: str, num: int = 10, site_filters: List[str] | None = None) -> List[str]:
    """
    Run a SerpAPI search for `query`. Optionally restrict to site_filters (list of domains).
    Returns top `num` result URLs (organic results).
    """
    query_key = f"q:{query}|sites:{','.join(site_filters) if site_filters else ''}|n:{num}"
    cache = load_cache()
    if query_key in cache:
        return cache[query_key]

    # build q param with site: filters
    q = query
    if site_filters:
        site_part = " OR ".join([f"site:{s}" for s in site_filters])
        q = f"{query} {site_part}"

    params = {
        "engine": "google",
        "q": q,
        "num": num,
        "api_key": SERPAPI_KEY,
    }

    resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"SerpAPI error {resp.status_code}: {resp.text}")

    data = resp.json()
    urls = []
    # SerpAPI returns 'organic_results' usually
    for r in data.get("organic_results", []):
        link = r.get("link") or r.get("url")
        if not link:
            # sometimes 'rich_snippet' or other fields contain links; skip those
            continue
        urls.append(link)

    # dedupe while preserving order
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    # store top num
    unique_urls = unique_urls[:num]

    # cache result
    cache[query_key] = unique_urls
    save_cache(cache)

    time.sleep(RATE_LIMIT_SEC)
    return unique_urls


if __name__ == "__main__":
    # quick interactive test
    print("Running quick SerpAPI test. Make sure SERPAPI_KEY in .env is valid.")
    q = "best wireless headphones under 3000"
    sites = ["amazon.in", "flipkart.com", "nykaa.com"]
    try:
        results = serp_search(q, num=12, site_filters=sites)
        print(f"Found {len(results)} URLs:")
        for i, u in enumerate(results, 1):
            print(f"{i:2d}. {u}")
    except Exception as e:
        print("Search failed:", e)
