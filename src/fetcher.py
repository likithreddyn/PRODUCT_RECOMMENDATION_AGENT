
# Fetch & parse product pages
# src/fetcher.py
"""
Fetch product pages and extract structured product data.
- Downloads HTML
- Extracts JSON-LD (schema.org Product)
- Falls back to HTML if JSON-LD missing
- Saves raw HTML + parsed product JSON
"""

import os
import json
import re
from urllib.parse import urlparse
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import extruct
from w3lib.html import get_base_url
# import site_parsers as a sibling module with fallback
try:
    from src.site_parsers import parse_for_domain
except ImportError:
    try:
        from site_parsers import parse_for_domain
    except ImportError:
        parse_for_domain = None  # Make it optional
from dotenv import load_dotenv

load_dotenv()

# Paths relative to src/
BASE_DIR = Path(__file__).resolve().parent.parent
PAGES_DIR = BASE_DIR / "data" / "pages"
PRODUCTS_DIR = BASE_DIR / "data" / "products"

PAGES_DIR.mkdir(parents=True, exist_ok=True)
PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/108.0.0.0 Safari/537.36"
    )
}

def _slugify(url: str) -> str:
    """
    Convert a URL into a safe filename.
    """
    parsed = urlparse(url)
    base = parsed.netloc.replace(".", "_")
    path = parsed.path.replace("/", "_")[:80]
    return f"{base}{path}"


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text



def _text_or_none(node):
    try:
        return node.get_text(strip=True) if node else None
    except Exception:
        return None

def _find_product_in_extruct(data: dict):
    """Find a 'Product' item in the data extracted by `extruct`."""
    for key in ['json-ld', 'microdata', 'rdfa']:
        for item in data.get(key, []):
            if isinstance(item, dict) and item.get('@type') == 'Product':
                return item
            if isinstance(item, dict):
                # Check for product in main entity
                if item.get('mainEntity', {}).get('@type') == 'Product':
                    return item.get('mainEntity')
                # Check for product in graph
                if '@graph' in item:
                    for graph_item in item['@graph']:
                        if isinstance(graph_item, dict) and graph_item.get('@type') == 'Product':
                            return graph_item
    return None

def fallback_extract(soup: BeautifulSoup):
    """
    Heavier fallback: try common selectors for Amazon / Flipkart / Nykaa
    and some generic heuristics (meta tags, JSON snippets, regex price).
    """
    title = _text_or_none(soup.select_one("#productTitle, h1, .prd-title, .pdp-title"))
    # description: meta description, or long description blocks
    desc = None
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc = meta_desc.get("content")
    if not desc:
        # try common description selectors
        dsel = soup.select_one("#productDescription, #feature-bullets, .product-desc, .description")
        desc = _text_or_none(dsel) or desc

    # price heuristics
    price = None
    price_selectors = [
        "#priceblock_ourprice", "#priceblock_dealprice", ".priceBlockBuyingPriceString",
        ".pdp-price", ".selling-price, ._30jeq3._16Jk6d", ".a-price-whole", ".price", ".final-price"
    ]
    for sel in price_selectors:
        node = soup.select_one(sel)
        if node:
            price_text = node.get_text(separator=" ", strip=True)
            if price_text:
                price = price_text
                break

    # regex fallback to find currency amounts
    if not price:
        txt = soup.get_text(separator=" ", strip=True)
        # wide regex for ₹, Rs., INR, ₹\s or numbers with commas
        m = re.search(r'(₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?', txt)
        if not m:
            # try number with comma and ₹ symbol nearby
            m = re.search(r'₹\s*[\d,]+', txt)
        if m:
            price = m.group(0)

    # reviews heuristics: try common selectors and JSON area
    reviews = []
    # JSON-LD 'review' fallback
    # Try to find any script tags containing "review" or "reviewBody"
    for s in soup.find_all("script"):
        if not s.string:
            continue
        if "reviewBody" in s.string or '"review"' in s.string:
            try:
                jd = json.loads(s.string)
                # if it's a dict with review or reviews
                if isinstance(jd, dict):
                    if "review" in jd:
                        rv = jd.get("review")
                        if isinstance(rv, list):
                            for r in rv[:5]:
                                if isinstance(r, dict):
                                    reviews.append(r.get("reviewBody") or r.get("description") or r.get("name"))
                        elif isinstance(rv, dict):
                            reviews.append(rv.get("reviewBody") or rv.get("description") or rv.get("name"))
                # if list
            except Exception:
                continue

    # common review selectors (Amazon / Flipkart)
    review_selectors = [
        ".review-text", ".a-size-base.review-text.review-text-content, .review-text-content", 
        ".qwjRop ._3l3x", "._16PBlm", ".col._2wzgFH", ".t-ZTKy", "._2-N8zT", "._1YokD2 ._1AtVbE"
    ]
    for sel in review_selectors:
        nodes = soup.select(sel)
        for n in nodes[:5]:
            txt = _text_or_none(n)
            if txt:
                reviews.append(txt)

    # keep unique small list
    seen = set()
    filtered = []
    for r in reviews:
        if not r:
            continue
        if r in seen:
            continue
        seen.add(r)
        filtered.append(r)
        if len(filtered) >= 5:
            break

    return {
        "name": title or "Unknown",
        "description": desc or "",
        "offers": {"price": price},
        "reviews": filtered
    }


def parse_product(url: str) -> dict:
    """
    Fetch + parse product info into a structured dict.
    """
    print(f"[fetcher] Fetching: {url}")

    html = fetch_html(url)
    base_url = get_base_url(html, url)
    soup = BeautifulSoup(html, "html.parser")

    # Use extruct to get all structured data
    data = extruct.extract(html, base_url=base_url, syntaxes=['json-ld', 'microdata', 'rdfa'])
    
    product_data = _find_product_in_extruct(data)

    if product_data:
        print("[fetcher] Found structured Product data.")
        # If we found a product, we can return it, maybe after some processing
        # For now, we just return the raw data
        data = product_data
    else:
        # Try site-specific parser first (amazon/flipkart/nykaa)
        try:
            domain = urlparse(url).netloc
            sp = parse_for_domain(domain, soup, url)
            if sp and isinstance(sp, dict) and sp.get("source_url"):
                print(f"[fetcher] Used site-specific parser for {domain}")
                data = sp
            else:
                print("[fetcher] Structured data missing, using generic fallback parser.")
                data = fallback_extract(soup)
        except Exception:
            print("[fetcher] site-specific parser failed, using generic fallback.")
            data = fallback_extract(soup)

    # Add the URL to the product data
    data["source_url"] = url

    return html, data


def save_product(url: str):
    """
    Fetch, parse, and save product HTML + structured JSON.
    """
    product_id = _slugify(url)
    html, data = parse_product(url)

    html_path = PAGES_DIR / f"{product_id}.html"
    json_path = PRODUCTS_DIR / f"{product_id}.json"

    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[fetcher] Saved HTML → {html_path}")
    print(f"[fetcher] Saved JSON → {json_path}")

    return json_path


if __name__ == "__main__":
    # Quick test with one URL
    test_url = "https://www.amazon.in/LEGO-Minifigures-Spider-Man-Spider-Verse-Building/dp/B0DWDQZ5LH/ref=sr_1_8?dib=eyJ2IjoiMSJ9.mfdRJ335oj7xAS5GUpTcDpQcQ3Dh5h43HW-W_jTmIfPvwj_WfpTRhA6GM1v_laBW84tIGTOCY5NxLGUA3NVxd1Tnsc5vq8EAAuTN1MV_3OcBo-7W0xM1DWNpzrkiDoYGI96j69HTrK6tiCJPj89Nok5-D1yPIkItjvTtv-U9HpnCIiOzq8MlFLnrQCTi3mCfVRAKCIvhnuoZ00iUqCnTw2t8DTE8EBhOAH8tpSRYomNH2Vi6fuew2RHGmBm8WFh0iRC0HxqF60cOHXQGlK3jgslfNNzfv4UM2H9Lw5ZKN7Y.blGmXYx5SmaQyQyWpsw3ZhdZK-tmg5ui5ViBlbAvpQA&dib_tag=se&keywords=lego&nsdOptOutParam=true&qid=1764447481&sr=8-8"
    save_product(test_url)
