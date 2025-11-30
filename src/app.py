# src/app.py
import streamlit as st
from pathlib import Path
import json
import time
from typing import Dict, Optional
import os
import re
import requests
from bs4 import BeautifulSoup

# local modules (must be importable from src/)
from serp_search import serp_search   # returns list of urls
from parser import save_product      # fetch + parse + normalize + save to data/products/<slug>.json
import indexer_minimal as indexer    # upsert_product_file(Path(json_path))

ROOT = Path(__file__).resolve().parent
PRODUCTS_DIR = ROOT.parent / "data" / "products"

st.set_page_config(page_title="Product Recommendation Agent", layout="wide")

# ---------------- fallback images (publicly available / Wikimedia or generic) ----------------
# Replace these URLs with images you prefer. They are public-friendly placeholders.
FALLBACK_IMAGES = {
    "iphone": "https://upload.wikimedia.org/wikipedia/commons/3/31/IPhone_14_Pro_Black.jpg",
    "headphones": "https://upload.wikimedia.org/wikipedia/commons/4/4e/Headphones.jpg",
    "default": "https://upload.wikimedia.org/wikipedia/commons/d/dd/No_image_available.svg"
}

# ---------------- helpers ----------------
def load_saved_product(json_path: Path) -> Dict:
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_saved_product(json_path: Path, data: Dict):
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def normalize_price_str(raw: Optional[str]) -> Optional[str]:
    """Return a canonical price string. Keep symbol if INR present."""
    if not raw:
        return None
    s = str(raw).strip()
    # prefer explicit rupee symbol
    m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', s)
    if m:
        return m.group(1).replace(' ', '')
    # Rs. or INR
    m = re.search(r'(Rs\.?\s*[\d,]+(?:\.\d+)?)', s, re.IGNORECASE)
    if m:
        return m.group(1).replace(' ', '')
    # numeric fallback (digits + commas + optional decimals)
    m = re.search(r'([\d][\d,]+(?:\.\d+)?)', s)
    if m:
        return m.group(1)
    return s or None

def pick_keyword_fallback_image(title: str) -> str:
    t = title.lower() if title else ""
    if "iphone" in t or "apple" in t:
        return FALLBACK_IMAGES["iphone"]
    if "headphone" in t or "earbud" in t:
        return FALLBACK_IMAGES["headphones"]
    return FALLBACK_IMAGES["default"]

def fetch_live_image_and_price(url: str) -> Dict[str, Optional[str]]:
    """
    Try many selectors to extract image and price from a product page.
    Return {"image": url_or_none, "price": string_or_none}
    """
    out = {"image": None, "price": None}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # --- IMAGE extraction attempts ---
        # 1) OpenGraph / Twitter
        og = soup.select_one('meta[property="og:image"], meta[name="og:image"]')
        if og and og.get("content"):
            out["image"] = og["content"]
        if not out["image"]:
            tw = soup.select_one('meta[name="twitter:image"]')
            if tw and tw.get("content"):
                out["image"] = tw["content"]
        if not out["image"]:
            lr = soup.select_one('link[rel="image_src"]')
            if lr and lr.get("href"):
                out["image"] = lr["href"]

        # 2) common product image selectors
        if not out["image"]:
            selectors = [
                'img#landingImage', 'img#imgBlkFront', 'img[data-a-dynamic-image]',
                '.product-image img', '.main-image img', '.product-photo img', '.gallery img'
            ]
            for sel in selectors:
                node = soup.select_one(sel)
                if node:
                    src = node.get("src") or node.get("data-src") or node.get("data-lazy-src")
                    if src and src.startswith("http"):
                        out["image"] = src
                        break

        # 3) any decent absolute image
        if not out["image"]:
            for node in soup.find_all("img", src=True):
                s = node["src"]
                if s and s.startswith("http") and len(s) > 20:
                    out["image"] = s
                    break

        # --- PRICE extraction attempts ---
        # Try many common selectors used by major e-commerce sites
        price_selectors = [
            "#priceblock_ourprice", "#priceblock_dealprice", ".a-price .a-offscreen", ".a-price-whole",
            ".priceBlockBuyingPriceString", ".pdp-price", ".selling-price", ".FinalPrice",
            ".price", ".product-price", ".offer-price", ".pprice", "._30jeq3._16Jk6d",
            ".price-whole", ".payBlkBig", ".priceLarge"
        ]
        for sel in price_selectors:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(" ", strip=True)
                cand = normalize_price_str(text)
                if cand:
                    out["price"] = cand
                    break

        # Regex search over visible text as fallback
        if not out["price"]:
            txt = soup.get_text(" ", strip=True)
            m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', txt)
            if m:
                out["price"] = m.group(1).replace(' ', '')
            else:
                m = re.search(r'(Rs\.?\s*[\d,]+(?:\.\d+)?)', txt, re.IGNORECASE)
                if m:
                    out["price"] = m.group(1).replace(' ', '')
                else:
                    # try find "price" nearby numbers
                    m = re.search(r'(?:price|mrp|₹|Rs\.?)\s*[:\-\s]?\s*([\d,]+\d(?:\.\d+)?)', txt, re.IGNORECASE)
                    if m:
                        out["price"] = m.group(1)

        return out
    except Exception as e:
        print(f"[fetch_live] failed for {url}: {e}")
        return out

def augment_and_save_product(json_path: Path):
    """
    Ensure the saved product JSON contains 'offers.price' (normalized) and 'images' list (has at least one).
    If missing, fetch live page, augment JSON, write back file, and return updated dict.
    """
    data = load_saved_product(json_path)
    if not data:
        return {}

    url = data.get("source_url") or data.get("url")
    title = (data.get("name") or data.get("title") or "").strip()

    # Try to get price from data structure first
    price = None
    try:
        price = data.get("offers", {}).get("price") or data.get("price")
    except Exception:
        price = None

    images = data.get("images") or []
    need_price = not price or str(price).strip() in ("", "n/a", "None", None)
    need_image = not images or len(images) == 0

    if (need_price or need_image) and url:
        meta = fetch_live_image_and_price(url)
        # image
        if need_image and meta.get("image"):
            images = [meta["image"]]
        # price
        if need_price and meta.get("price"):
            price = normalize_price_str(meta["price"])

    # Still missing image -> keyword fallback
    if not images or len(images) == 0:
        fallback = pick_keyword_fallback_image(title)
        images = [fallback]

    # Ensure nested structure offers.price
    if price:
        if "offers" not in data or not isinstance(data["offers"], dict):
            data["offers"] = {}
        data["offers"]["price"] = price

    # set images array
    data["images"] = images

    # write back canonical JSON file
    try:
        write_saved_product(json_path, data)
    except Exception as e:
        print(f"[augment] failed to write {json_path}: {e}")

    return data

def render_product_card_from_json(data: Dict, idx: int):
    title = data.get("name") or data.get("title") or "Unknown"
    price = data.get("offers", {}).get("price") or data.get("price") or "n/a"
    images = data.get("images") or []
    img = images[0] if images else None
    url = data.get("source_url") or data.get("url") or ""

    st.markdown(f"**{idx}. {title}**")
    cols = st.columns([1,4])
    with cols[0]:
        if img:
            try:
                st.image(img, width=140)
            except Exception:
                st.write("No image")
        else:
            st.write("No image")
    with cols[1]:
        st.write(f"**Price:** {price}")
        if url:
            st.markdown(f"[Open product page]({url})")
        desc = data.get("description") or ""
        if desc:
            st.write(desc[:300] + ("" if len(desc) < 300 else "..."))

# ---------------- UI ----------------
st.title("🛍️ Product Recommendation Agent")
st.write("Type product name, click Search → agent will fetch, augment and index products automatically (background).")

# Sidebar / Search settings
st.sidebar.header("Search / quick settings")
query = st.sidebar.text_input("Search query (type product name then click Search)", value="")
num_results = st.sidebar.slider("Search results to fetch", 1, 8, 5)
site_filters = st.sidebar.text_input("Site filters (comma separated, optional)", value="amazon.in,flipkart.com,nykaa.com")
search_button = st.sidebar.button("Search")

# QA area
st.subheader("Ask a question (after picking a product)")
question = st.text_area("Your question (be specific)", value="What is its cost?")
product_choice = st.text_input("Product URL or exact title (optional)", value="")
ask_btn = st.button("Ask product assistant")

# cards area
st.subheader("Products")
cards_container = st.container()

# ---------------- main pipeline triggered by Search ----------------
if search_button:
    if not query.strip():
        st.sidebar.error("Please type a product name before clicking Search.")
    else:
        with st.spinner("Searching, fetching and indexing products — this runs automatically (may take a moment)..."):
            filters = [s.strip() for s in site_filters.split(",") if s.strip()]
            try:
                urls = serp_search(query, num=num_results, site_filters=filters if filters else None)
            except Exception as e:
                st.sidebar.error(f"Search failed: {e}")
                urls = []

            if not urls:
                st.sidebar.info("No results returned by search.")
            else:
                saved_json_paths = []
                for u in urls:
                    try:
                        ppath = save_product(u)   # should persist data/products/<slug>.json
                        if isinstance(ppath, Path):
                            ppath = str(ppath)
                        # ensure we have a path string pointing to json file
                        saved_json_paths.append(ppath)
                        time.sleep(0.35)
                    except Exception as e:
                        print(f"[app] fetch/parse failed for {u}: {e}")
                        continue

                # augment saved JSONs (price + image) and write them back; then upsert to index
                augmented_paths = []
                for pjson in saved_json_paths:
                    try:
                        ppath = Path(pjson)
                        updated = augment_and_save_product(ppath)  # modifies file in-place
                        # upsert to index (indexer must provide upsert_product_file)
                        try:
                            indexer.upsert_product_file(ppath)
                        except Exception as ie:
                            print(f"[index] upsert failed for {ppath}: {ie}")
                        augmented_paths.append(ppath)
                    except Exception as e:
                        print(f"[app] augment failed for {pjson}: {e}")
                        continue

                # display cards using augmented JSONs
                with cards_container:
                    for i, ppath in enumerate(augmented_paths, start=1):
                        data = load_saved_product(Path(ppath))
                        render_product_card_from_json(data, i)

# Ask QA
if ask_btn:
    if not question.strip():
        st.error("Please enter a question.")
    else:
        try:
            from qa import answer_question
            pq = product_choice.strip() or query
            with st.spinner("Getting answer from product assistant..."):
                ans = answer_question(question, product_query=pq, top_k=3)
            st.success("Answer")
            st.write(ans)
        except Exception as e:
            st.error(f"QA failed: {e}")
            print("QA exception:", e)
