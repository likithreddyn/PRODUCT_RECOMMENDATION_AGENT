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

# Read API key but do NOT raise at import time — allow the app to import
# even when the key isn't present so Streamlit can render an error message
# instead of failing to import the module.
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

# Basic config
SERPAPI_ENDPOINT = "https://serpapi.com/search"
# Make cache path absolute and deterministic relative to the repo (src/../data/pages)
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "pages" / "urls_cache.json"
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


def _is_product_page(url: str) -> bool:
    """
    Heuristic to detect if URL is a SINGLE product page (not category/search/listing).
    Returns True ONLY if it's clearly an individual product page.
    Returns False for search results, category pages, listings, etc.
    """
    url_lower = url.lower()
    
    # MUST EXCLUDE - these are definitely multi-product pages
    exclude_patterns = [
        "/s?k=",          # Amazon search with keyword
        "/s/",            # Amazon search shorthand
        "/search",        # Generic search
        "/browse",        # Category browse
        "/category",      # Category page
        "/categories",    # Categories listing
        "/collections",   # Collections
        "/shop",          # Shop listing
        "?s=",            # Query string search
        "search?",        # Search endpoint
        "results",        # Results page
        "/filter",        # Filter page
        "/sort",          # Sort page
        "bestsellers",    # Best sellers list
        "new-arrivals",   # New arrivals list
        "/all-products",  # All products page
        "/specials",      # Specials/deals page
        "/b/",            # Amazon browse (category)
        "/gp/bestsellers",# Bestsellers
        "/deals",         # Deals page
        "?node=",         # Category node
        "&node=",         # Category in query
        "/page",          # Pagination
    ]
    
    for pattern in exclude_patterns:
        if pattern in url_lower:
            return False
    
    # MUST INCLUDE - these are definitely individual product pages
    include_patterns = [
        "/dp/",           # Amazon individual product
        "/product/",      # Generic product page
        "/p/",            # Short product
        "/item/",         # Item page
        "/products/",     # Products detail
    ]
    
    for pattern in include_patterns:
        if pattern in url_lower:
            return True
    
    # If it has a product ID-like pattern (like /B0FQFYXCC4), likely individual product
    if any(site in url_lower for site in ["amazon.in/", "amazon.com/"]):
        # Amazon URLs should have /dp/ or similar product identifier
        import re
        # Check for product ID patterns (B0xxxxx or similar)
        if re.search(r'/[Bb]0[A-Z0-9]{7,}', url_lower):
            return True
        return False  # Reject other Amazon URLs
    
    # For Flipkart, must have /p/ or /product/
    if "flipkart.com" in url_lower or "flipkart.in" in url_lower:
        if "/p/" in url_lower or "/product/" in url_lower:
            return True
        return False  # Reject other Flipkart URLs
    
    # For Myntra, must have /p/ or /product/
    if "myntra.com" in url_lower:
        if "/p/" in url_lower or "/product/" in url_lower:
            return True
        return False
    
    # For Nykaa, must have /p/ or /product/
    if "nykaa.com" in url_lower:
        if "/p/" in url_lower or "/product/" in url_lower:
            return True
        return False
    
    # For Snapdeal, must have /product/
    if "snapdeal.com" in url_lower:
        if "/product/" in url_lower:
            return True
        return False
    
    # Default: reject unknown patterns
    return False


def serp_search(query: str, num: int = 10, site_filters: List[str] | None = None) -> List[str]:
    """
    Run a SerpAPI search for `query`. Optionally restrict to site_filters (list of domains).
    Returns top `num` result URLs (organic results), filtered to exclude category/listing pages.
    """
    # fail fast with a helpful message if API key is missing
    if not SERPAPI_KEY:
        raise RuntimeError("SERPAPI_KEY not found. Add it to your .env file or set the environment variable.")
    query_key = f"q:{query}|sites:{','.join(site_filters) if site_filters else ''}|n:{num}"
    cache = load_cache()
    if query_key in cache:
        return cache[query_key]

    # build q param with site: filters (force Indian sites .in only)
    q = query
    # always restrict to Indian domains only
    indian_sites = [s for s in (site_filters or []) if '.in' in s or 'flipkart' in s or 'myntra' in s or 'snapdeal' in s]
    if not indian_sites:
        # if user didn't provide .in sites, use all Indian e-commerce sites
        indian_sites = ["amazon.in", "flipkart.com", "myntra.com", "nykaa.com", "snapdeal.com"]
    site_part = " OR ".join([f"site:{s}" for s in indian_sites])
    q = f"{query} {site_part}"

    params = {
        "engine": "google",
        "q": q,
        "num": num * 2,  # fetch 2x to account for filtering out multi-product pages
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
        # Filter out category, listing, search result pages
        if _is_product_page(link):
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
