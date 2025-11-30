"""Site-specific parsers for Amazon, Flipkart, Nykaa.
Each parser accepts a BeautifulSoup `soup` and `url` and returns a dict with
keys: name, description, offers: {price}, images: [..], reviews: [..]

These are best-effort selectors to improve extraction accuracy for those sites.
"""
from bs4 import BeautifulSoup
import re
from typing import Dict, List


def _collect_reviews_by_selectors(soup: BeautifulSoup, selectors: List[str], limit: int = 5):
    out = []
    seen = set()
    for sel in selectors:
        for node in soup.select(sel):
            txt = node.get_text(" ", strip=True)
            if not txt:
                continue
            if txt in seen:
                continue
            seen.add(txt)
            out.append(txt)
            if len(out) >= limit:
                return out
    return out


def parse_amazon(soup: BeautifulSoup, url: str) -> Dict:
    title = (soup.select_one('#productTitle') or soup.select_one('h1')).get_text(strip=True) if soup.select_one('#productTitle') or soup.select_one('h1') else None
    desc_node = soup.select_one('#productDescription') or soup.select_one('#feature-bullets')
    desc = desc_node.get_text(" ", strip=True) if desc_node else None

    # image candidates (try og:image, then common amazon selectors, then any http image)
    img = None
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get('content'):
        img = og['content']
    if not img:
        # Try multiple Amazon image selectors
        candidates = [
            'img#landingImage',
            'img[data-old-hires]',
            'img[alt*="product"]',
            'img.a-dynamic-image',
            '#altImages img',
            'img[data-a-dynamic-image]',
        ]
        for sel in candidates:
            node = soup.select_one(sel)
            if node:
                src = node.get('src') or node.get('data-old-hires') or node.get('data-a-dynamic-image')
                if src and src.startswith('http') and len(src) > 50:
                    img = src
                    break
    if not img:
        # fallback: find any image with reasonable size
        for img_node in soup.find_all('img'):
            src = img_node.get('src') or img_node.get('data-src') or img_node.get('data-a-dynamic-image')
            if src and src.startswith('http') and len(src) > 50 and 'amazon' in src.lower():
                img = src
                break

    # price (try multiple selectors, then regex)
    price = None
    price_selectors = [
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.a-price .a-offscreen',
        '.a-price-whole',
        'span.a-price-whole',
        'span[data-a-color*="price"]',
        'span.a-price-symbol',
        'div.a-price',
        '.a-price.a-text-price.a-size-medium.apexPriceToPay',
    ]
    for sel in price_selectors:
        nodes = soup.select(sel)
        for node in nodes:
            txt = node.get_text(" ", strip=True)
            m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
            if m:
                price = m.group(1)
                break
        if price:
            break
    if not price:
        txt = soup.get_text(" ", strip=True)
        m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
        if m:
            price = m.group(1)

    # reviews
    review_selectors = [
        "div[data-hook='review'] .review-text-content",
        "#cm-cr-dp-review-list .review-text",
        ".review-text",
        "span[data-hook='review-body']",
        "div.a-row.a-spacing-small",
    ]
    reviews = _collect_reviews_by_selectors(soup, review_selectors, limit=5)

    return {
        "name": title or "",
        "description": desc or "",
        "offers": {"price": price},
        "images": [img] if img else [],
        "reviews": reviews,
        "source_url": url,
    }


def parse_flipkart(soup: BeautifulSoup, url: str) -> Dict:
    title = (soup.select_one('span.B_NuCI') or soup.select_one('h1') or soup.select_one('.yhB1nd')).get_text(strip=True) if (soup.select_one('span.B_NuCI') or soup.select_one('h1') or soup.select_one('.yhB1nd')) else None
    desc_node = soup.select_one('div._1mXcCf') or soup.select_one('div._2mQ9ls') or soup.select_one('div.product-description')
    desc = desc_node.get_text(" ", strip=True) if desc_node else None

    # image candidates
    img = None
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get('content'):
        img = og['content']
    if not img:
        # Try multiple Flipkart image selectors
        candidates = [
            'img._2r_T1I',
            'img[alt*="product"]',
            'img[data-src]',
            '.fHxXCd img',
            'img.EKtt6',
        ]
        for sel in candidates:
            node = soup.select_one(sel)
            if node:
                src = node.get('src') or node.get('data-src')
                if src and src.startswith('http') and len(src) > 50:
                    img = src
                    break
    if not img:
        # fallback: find any image with reasonable size from flipkart cdn
        for img_node in soup.find_all('img'):
            src = img_node.get('src') or img_node.get('data-src')
            if src and src.startswith('http') and len(src) > 50 and ('flipkart' in src.lower() or 'cloudinary' in src.lower()):
                img = src
                break

    # price
    price = None
    price_selectors = [
        'div._30jeq3._16Jk6d',
        'div._1vC4OE',
        'span._16Jk6d',
        '.price',
        'span._2Tpremove',
        'div.Nx9bqj',
        'div._25b27d',
    ]
    for sel in price_selectors:
        nodes = soup.select(sel)
        for node in nodes:
            txt = node.get_text(" ", strip=True)
            m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
            if m:
                price = m.group(1)
                break
        if price:
            break
    if not price:
        txt = soup.get_text(" ", strip=True)
        m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
        if m:
            price = m.group(1)

    # reviews
    review_selectors = [
        'div._16PBlm',
        'div._1lRcqv',
        'div._2-N8zT',
        'div._3n65Vw',
        'span._2MQATc',
        'p._39M2dY',
    ]
    reviews = _collect_reviews_by_selectors(soup, review_selectors, limit=5)

    return {
        "name": title or "",
        "description": desc or "",
        "offers": {"price": price},
        "images": [img] if img else [],
        "reviews": reviews,
        "source_url": url,
    }


def parse_nykaa(soup: BeautifulSoup, url: str) -> Dict:
    title = (soup.select_one('h1') or soup.select_one('.css-1x7n0ad') ).get_text(strip=True) if (soup.select_one('h1') or soup.select_one('.css-1x7n0ad')) else None
    desc_node = soup.select_one('.css-1r4v2tw') or soup.select_one('.product-description') or soup.select_one('[data-testid="productDescription"]')
    desc = desc_node.get_text(" ", strip=True) if desc_node else None

    # image candidates
    img = None
    og = soup.select_one('meta[property="og:image"]')
    if og and og.get('content'):
        img = og['content']
    if not img:
        # Try multiple Nykaa image selectors
        candidates = [
            'img[alt*="product"]',
            'img[data-src]',
            '.slick-active img',
            'img.slick-slide',
            'img[src*="images.nykaa"]',
        ]
        for sel in candidates:
            node = soup.select_one(sel)
            if node:
                src = node.get('src') or node.get('data-src')
                if src and src.startswith('http') and len(src) > 50:
                    img = src
                    break
    if not img:
        # fallback: find any image with reasonable size from Nykaa CDN
        for img_node in soup.find_all('img'):
            src = img_node.get('src') or img_node.get('data-src')
            if src and src.startswith('http') and len(src) > 50 and ('nykaa' in src.lower() or 'images' in src.lower()):
                img = src
                break

    # price
    price = None
    price_selectors = [
        '.css-11m7h9r',
        '.css-1jczs19',
        '.price',
        'span[data-testid="priceTagAmount"]',
        'span[data-testid="productPrice"]',
        '.price-tag',
        'span.css-15r0p3f',
    ]
    for sel in price_selectors:
        nodes = soup.select(sel)
        for node in nodes:
            txt = node.get_text(" ", strip=True)
            m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
            if m:
                price = m.group(1)
                break
        if price:
            break
    if not price:
        txt = soup.get_text(" ", strip=True)
        m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
        if m:
            price = m.group(1)

    review_selectors = [
        '.css-1g7m0tk .css-1r0v9b1',
        '.css-1t8l7ad',
        '.review',
        'span[data-testid="rating"]',
        'p[data-testid="reviewText"]',
    ]
    reviews = _collect_reviews_by_selectors(soup, review_selectors, limit=5)

    return {
        "name": title or "",
        "description": desc or "",
        "offers": {"price": price},
        "images": [img] if img else [],
        "reviews": reviews,
        "source_url": url,
    }


def parse_for_domain(domain: str, soup: BeautifulSoup, url: str) -> Dict:
    d = domain.lower()
    if 'amazon' in d:
        return parse_amazon(soup, url)
    if 'flipkart' in d:
        return parse_flipkart(soup, url)
    if 'nykaa' in d:
        return parse_nykaa(soup, url)
    # unknown domain — return empty dict
    return {}
