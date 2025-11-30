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



def extract_json_ld(soup: BeautifulSoup):
    """
    More robust JSON-LD extraction:
    - handles dict, list, @graph structures
    - looks for Product objects anywhere in JSON-LD
    """
    scripts = soup.find_all("script", {"type": "application/ld+json"})
    for s in scripts:
        raw = s.string
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            # some pages include multiple JSON objects glued together; try to split heuristically
            try:
                chunks = re.split(r'\}\s*\{', raw)
                for i, chunk in enumerate(chunks):
                    maybe = chunk
                    if not chunk.startswith('{'):
                        maybe = '{' + chunk
                    if not chunk.endswith('}'):
                        maybe = maybe + '}'
                    try:
                        jd = json.loads(maybe)
                        # check jd below similarly
                        if isinstance(jd, dict):
                            # check for Product or parse @graph
                            if jd.get("@type") in ("Product", "product"):
                                return jd
                            if "@graph" in jd and isinstance(jd["@graph"], list):
                                for item in jd["@graph"]:
                                    if item.get("@type") in ("Product", "product"):
                                        return item
                    except Exception:
                        continue
            except Exception:
                continue

        # Now data is a parsed JSON object or list
        if isinstance(data, dict):
            # direct Product
            if data.get("@type") in ("Product", "product"):
                return data
            # graph style
            if "@graph" in data and isinstance(data["@graph"], list):
                for obj in data["@graph"]:
                    if isinstance(obj, dict) and obj.get("@type") in ("Product", "product"):
                        return obj
            # sometimes nested under 'mainEntity'
            if "mainEntity" in data and isinstance(data["mainEntity"], dict) and data["mainEntity"].get("@type") in ("Product", "product"):
                return data["mainEntity"]
        elif isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict) and obj.get("@type") in ("Product", "product"):
                    return obj
    return None


def _text_or_none(node):
    try:
        return node.get_text(strip=True) if node else None
    except Exception:
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
    soup = BeautifulSoup(html, "html.parser")

    # try JSON-LD extraction
    data = extract_json_ld(soup)
    if data:
        print("[fetcher] Found JSON-LD Product data.")
    else:
        # Try site-specific parser first (amazon/flipkart/nykaa)
        try:
            domain = urlparse(url).netloc
            sp = parse_for_domain(domain, soup, url)
            if sp and isinstance(sp, dict) and sp.get("source_url"):
                print(f"[fetcher] Used site-specific parser for {domain}")
                data = sp
            else:
                print("[fetcher] JSON-LD missing, using generic fallback parser.")
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
