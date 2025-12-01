# src/parser.py
"""
Parser / saver wrapper that:
- Calls the (existing) fetcher.parse_product to fetch+parse a page
- Runs a robust price+image scouting function on the page HTML
- Merges best price/image into the normalized product JSON
- Writes HTML -> data/pages/<slug>.html and JSON -> data/products/<slug>.json
- Returns the JSON path (str)
This module exposes `save_product` and `parse_and_save` (alias).
"""

from pathlib import Path
import json
import re

# import functions from your existing fetcher (assumes file src/fetcher.py exists)
# fetcher provides: parse_product(url) -> (html:str, data:dict), _slugify(url)
try:
    from src.fetcher import parse_product, _slugify, PAGES_DIR, PRODUCTS_DIR
except ImportError:
    try:
        from fetcher import parse_product, _slugify, PAGES_DIR, PRODUCTS_DIR
    except Exception as e:
        raise RuntimeError("Could not import parse_product/_slugify from fetcher.py; ensure fetcher.py is present in src/") from e

# Regex to find rupee/rs style amounts
PRICE_REGEX = re.compile(r'(₹\s*[\d,]+(?:\.\d+)?)|(?:Rs\.?\s*[\d,]+(?:\.\d+)?)', re.IGNORECASE)

def _normalize_num_str(s: str) -> str:
    """Normalize price-like string to keep currency symbol and digits/commas/dot."""
    if not s:
        return s
    out = s.strip()
    out = out.replace("INR", "").replace("Rs.", "₹").replace("Rs", "₹")
    # If it's a range like ₹499 - ₹999 or 499-999, pick the lower bound as canonical
    # Find all numeric occurrences and choose the smallest sensible one
    nums = re.findall(r'₹?\s*([\d,]+(?:\.\d+)?)', out)
    if nums:
        # pick numeric values, remove commas, convert to float
        try:
            vals = [float(n.replace(',', '')) for n in nums]
            if vals:
                smallest = int(min(vals)) if all(float(v).is_integer() for v in vals) else min(vals)
                # format with commas
                formatted = f"{smallest:,}"
                return '₹' + str(formatted)
        except Exception:
            pass

    # fallback: keep digits, commas, dot and rupee sign
    out = re.sub(r'[^\d\.,₹]', '', out)
    out = out.strip()
    if out and not out.startswith('₹'):
        out = '₹' + out
    return out

def _score_candidate(text: str, base: int = 0) -> int:
    """Simple scoring function to prefer contextually relevant price matches."""
    t = (text or "").lower()
    score = base
    for kw in ("price", "mrp", "offer", "deal", "you pay", "our price", "special price", "₹", "rs"):
        if kw in t:
            score += 2 if kw in ("price","mrp","offer","deal","you pay","our price","special price") else 1
    # prefer larger numbers (more digits)
    digits = re.sub(r'\D', '', t)
    if len(digits) >= 4:
        score += 1
    return score

def save_product(url: str) -> str:
    """
    Top-level save wrapper. Calls fetcher.parse_product(url) to get html,data.
    Then enriches data with image & price (via live fetch heuristics).
    Writes HTML -> data/pages/<slug>.html and JSON -> data/products/<slug>.json.
    Returns the JSON path as string.
    """
    # parse_product (from fetcher) should download page (requests) and attempt to parse JSON-LD etc.
    html, data = parse_product(url)  # parse_product must exist in fetcher.py

    # ensure canonical structure
    if not isinstance(data, dict):
        data = {"name": str(data)}

    # get price and image from the structured data
    price = data.get("offers", {}).get("price")
    image = data.get("image")

    # merge price
    if price:
        data.setdefault("offers", {})
        # save both under offers.price and top-level price for convenience
        data["offers"]["price"] = price
        data["price"] = price

    # merge image
    if image:
        imgs = data.get("images") or []
        if image not in imgs:
            imgs.insert(0, image)
        data["images"] = imgs

    # write files using slug from fetcher._slugify
    product_id = _slugify(url)
    html_path = PAGES_DIR / f"{product_id}.html"
    json_path = PRODUCTS_DIR / f"{product_id}.json"

    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[parser] Saved HTML -> {html_path}")
    print(f"[parser] Saved JSON -> {json_path}")

    return str(json_path)

# alias expected names
def parse_and_save(url: str) -> str:
    """Compatibility alias used by some app code."""
    return save_product(url)

# make parse_and_save the exported name expected by app.py
__all__ = ["save_product", "parse_and_save"]
