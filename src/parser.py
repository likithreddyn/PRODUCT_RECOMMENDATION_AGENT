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
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict

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

def fetch_image_and_price_from_url(url: str, timeout: int = 12) -> Dict[str, Optional[str]]:
    """
    Best-effort fetch of page and extraction of image + price candidates.
    Returns dict: {"image": str|None, "price": str|None}
    """
    out = {"image": None, "price": None}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # 1) image candidates: og:image, twitter:image, link image_src
        def _abs(u):
            if not u:
                return None
            u = u.strip()
            if u.startswith('//'):
                return 'https:' + u
            if u.startswith('/'): 
                # resolve relative to page URL
                from urllib.parse import urljoin
                return urljoin(url, u)
            return u

        og = soup.select_one('meta[property="og:image"], meta[name="og:image"]')
        if og and og.get("content"):
            out["image"] = _abs(og.get("content"))
        if not out["image"]:
            tw = soup.select_one('meta[name="twitter:image"]')
            if tw and tw.get("content"):
                out["image"] = _abs(tw.get("content"))
        if not out["image"]:
            lr = soup.select_one('link[rel="image_src"]')
            if lr and lr.get("href"):
                out["image"] = _abs(lr.get("href"))

        # Additional lazy-load attributes and srcset handling
        if not out["image"]:
            # check for data-old-hires, data-src, data-srcset, data-a-dynamic-image
            img = None
            selectors = [
                'img[data-old-hires]', 'img[data-src]', 'img[data-srcset]', 'img[data-a-dynamic-image]', 'img[srcset]', 'img[src]'
            ]
            for sel in selectors:
                node = soup.select_one(sel)
                if node:
                    # prefer data-src/data-old-hires
                    for attr in ('data-old-hires','data-src','data-srcset','data-a-dynamic-image','srcset','src'):
                        val = node.get(attr)
                        if not val:
                            continue
                        if attr == 'data-a-dynamic-image':
                            # this is often a JSON mapping string
                            try:
                                jd = json.loads(val)
                                if isinstance(jd, dict):
                                    # get first URL
                                    candidate = next(iter(jd.keys()), None)
                                    if candidate:
                                        img = candidate
                                        break
                            except Exception:
                                # ignore parse error
                                pass
                        else:
                            # srcset and data-srcset may contain multiple URLs; take first
                            if ',' in val:
                                val = val.split(',')[0].split()[0]
                            img = val
                            break
                    if img:
                        out['image'] = _abs(img)
                        break

        # as last resort, pick first sufficiently long image src
        if not out["image"]:
            for img_tag in soup.find_all('img'):
                src = img_tag.get('data-src') or img_tag.get('data-original') or img_tag.get('data-lazy-src') or img_tag.get('src')
                if not src:
                    continue
                src = _abs(src)
                if not src:
                    continue
                # skip tiny or placeholder images
                if any(x in src.lower() for x in ('spinner','blank','pixel','placeholder')):
                    continue
                if len(src) > 40 and src.startswith('http'):
                    out['image'] = src
                    break

        # 2) preferred selectors for price (major sites)
        preferred_selectors = [
            "#priceblock_ourprice", "#priceblock_dealprice",
            ".a-price .a-offscreen", "span._30jeq3", ".pdp-price",
            ".selling-price", ".payBlkBig", ".product-price", ".offer-price",
            ".FinalPrice", ".priceBlockBuyingPriceString", ".price"
        ]
        candidates = []
        for sel in preferred_selectors:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(" ", strip=True)
                m = PRICE_REGEX.search(text)
                if m:
                    norm = _normalize_num_str(m.group(0))
                    candidates.append((norm, _score_candidate(text, base=4), f"sel:{sel}"))

        # 3) JSON-LD scanning
        for s in soup.find_all("script", {"type": "application/ld+json"}):
            txt = s.string or ""
            if "price" in txt.lower() or "offers" in txt.lower():
                for m in PRICE_REGEX.finditer(txt):
                    norm = _normalize_num_str(m.group(0))
                    candidates.append((norm, _score_candidate(txt, base=3), "json-ld"))

        # 4) fallback: scan body text and collect matches with context scoring
        page_text = soup.get_text(" ", strip=True)
        for m in PRICE_REGEX.finditer(page_text):
            ctx_start = max(0, m.start() - 120)
            ctx_end = min(len(page_text), m.end() + 120)
            ctx = page_text[ctx_start:ctx_end]
            norm = _normalize_num_str(m.group(0))
            candidates.append((norm, _score_candidate(ctx, base=0), f"context:{ctx[:80]}..."))

        # choose best candidate by aggregated score + frequency + numeric magnitude
        if candidates:
            agg = {}
            for norm, score, src in candidates:
                stat = agg.get(norm)
                if not stat:
                    agg[norm] = {"score": score, "count": 1}
                else:
                    stat["score"] = max(stat["score"], score)
                    stat["count"] += 1
            # select best (score, count, magnitude)
            best_key = None
            best_val = None
            for k, v in agg.items():
                digits = float(re.sub(r'[^\d.]', '', k) or 0)
                val = (v["score"], v["count"], digits)
                if best_val is None or val > best_val:
                    best_val = val
                    best_key = k
            out["price"] = best_key

        # review extraction: expand heuristics to include class-based and itemprop-based reviews
        reviews = []
        # JSON-LD 'review' fallback handled earlier in candidates; also try to parse review blocks
        review_selectors = [
            ".review-text", ".a-size-base.review-text.review-text-content", 
            ".review-text-content", ".customer-review", ".customerReview", ".review",
            "[itemprop=review]", "[data-reviewid]", ".crI"
        ]
        for sel in review_selectors:
            for n in soup.select(sel):
                txt = n.get_text(" ", strip=True)
                if txt and txt not in reviews:
                    reviews.append(txt)
                if len(reviews) >= 5:
                    break
            if len(reviews) >= 5:
                break

        if reviews and not out.get('reviews'):
            out['reviews'] = reviews

        return out

        return out
    except Exception as e:
        # best-effort: don't crash
        print(f"[parser.fetch_image_and_price_from_url] failed for {url}: {e}")
        return out

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

    # get live meta (best-effort)
    meta = fetch_image_and_price_from_url(url)
    price = meta.get("price")
    image = meta.get("image")

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
__all__ = ["save_product", "parse_and_save", "fetch_image_and_price_from_url"]



