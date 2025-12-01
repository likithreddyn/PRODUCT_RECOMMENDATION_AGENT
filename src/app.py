# src/app.py
import streamlit as st
from pathlib import Path
import json
import time
import re
from typing import Dict, Optional

# local modules (must be importable from src/)
from serp_search import serp_search   # returns list of urls
from parser import save_product      # fetch + parse + normalize + save to data/products/<slug>.json
import indexer_minimal as indexer    # upsert_product_file(Path(json_path))

# Initialize session state for chatbot
if "chat_question" not in st.session_state:
    st.session_state.chat_question = ""
if "chat_answer" not in st.session_state:
    st.session_state.chat_answer = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

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
    
    # Clean up common non-price text
    s = s.replace("Starting at", "").replace("From", "").replace("As low as", "").strip()
    
    # prefer explicit rupee symbol
    m = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', s)
    if m:
        return m.group(1).replace(' ', '')
    # Rs. or INR
    m = re.search(r'(Rs\.?\s*[\d,]+(?:\.\d+)?)', s, re.IGNORECASE)
    if m:
        return m.group(1).replace(' ', '')
    # numeric fallback with commas (digits + commas + optional decimals)
    m = re.search(r'([\d][\d,]*(?:\.\d+)?)', s)
    if m:
        price_str = m.group(1)
        # if it looks like a valid price (at least 2-3 digits or has commas)
        if len(re.sub(r'\D', '', price_str)) >= 2:
            return '₹' + price_str
    return s or None

def pick_keyword_fallback_image(title: str) -> str:
    t = title.lower() if title else ""
    if "iphone" in t or "apple" in t:
        return FALLBACK_IMAGES["iphone"]
    if "headphone" in t or "earbud" in t:
        return FALLBACK_IMAGES["headphones"]
    return FALLBACK_IMAGES["default"]

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
    
    # Still missing image -> keyword fallback
    if not images or len(images) == 0:
        fallback = pick_keyword_fallback_image(title)
        images = [fallback]

    # Ensure nested structure offers.price
    if price:
        if "offers" not in data or not isinstance(data["offers"], dict):
            data["offers"] = {}
        data["offers"]["price"] = normalize_price_str(price)

    # set images array (ensure at least one valid image)
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
num_results = st.sidebar.slider("Search results to fetch", 1, 20, 10)
# use only Indian (.in) e-commerce sites
DEFAULT_SITES = ["amazon.in", "flipkart.com", "myntra.com", "nykaa.com", "snapdeal.com"]
site_filters = ",".join(DEFAULT_SITES)
search_button = st.sidebar.button("Search")

# cards area
st.subheader("Products")
cards_container = st.container()

# --------- Render products + comparison + chatbot from session (persist across reruns) ---------
def _render_products_and_chat():
    prods = st.session_state.get('last_products')
    last_query = st.session_state.get('last_query', '')
    if not prods:
        return

    # product cards - individual cards with images, prices, links
    with cards_container:
        st.write(f"Showing results for: **{last_query}**")
        
        for idx, p in enumerate(prods, start=1):
            # Create individual product card with columns
            card_col1, card_col2, card_col3 = st.columns([1, 2, 1])
            
            # Image column (left)
            with card_col1:
                if p.get("image"):
                    try:
                        st.image(p.get("image"), width=150, caption=f"Product {idx}")
                    except Exception:
                        st.markdown(f"**[Image]**")
                else:
                    st.markdown("📷 No image")
            
            # Title, description, price (middle)
            with card_col2:
                badge = " ✅ Top Recommendation" if idx == 1 else ""
                st.markdown(f"### {idx}. {p['title']}{badge}")
                
                # Price (prominent)
                price_color = "🟢" if idx <= 3 else "⚪"
                st.markdown(f"### {price_color} **Price:** {p['price']}")
                
                # Description
                desc = load_saved_product(Path(p["path"])).get("description") or ""
                if desc:
                    st.caption(desc[:180] + ("..." if len(desc) > 180 else ""))
                
                # Reviews count
                reviews_count = len(p.get("reviews") or [])
                st.write(f"📝 {reviews_count} reviews available")
            
            # Link column (right)
            with card_col3:
                if p.get("url"):
                    st.markdown(f"### [🔗 Open Product]({p['url']})")
                    st.caption("Click to view on\ne-commerce site")
                else:
                    st.markdown("**No link**")
            
            # Divider between cards
            st.divider()

    # comparison table
    comp = []
    for rank, p in enumerate(prods[:10], start=1):
        comp.append({
            "rank": rank,
            "title": p["title"],
            "price": p["price"],
            "reviews": len(p.get("reviews") or []),
            "url": p.get("url")
        })

    st.subheader("Comparison: Top products")
    try:
        import pandas as _pd
        df = _pd.DataFrame(comp)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=False,
            column_config={
                "rank": st.column_config.NumberColumn("Rank", width="small"),
                "title": st.column_config.TextColumn("Product Title", width="large"),
                "price": st.column_config.TextColumn("Price", width="medium"),
                "reviews": st.column_config.NumberColumn("Reviews", width="small"),
                "url": st.column_config.LinkColumn("Link", width="medium")
            }
        )
    except Exception:
        st.table(comp)

    # Chatbot area (persistent) - keep input and history here
    st.subheader("Product Assistant Chatbot")
    st.write("Ask a question about the products shown above:")

    chat_col1, chat_col2 = st.columns([3, 1])
    with chat_col1:
        user_q = st.text_input(
            "Your question:",
            value=st.session_state.get('chat_question', ''),
            key="chat_input",
            placeholder="e.g., Which iPhone is the best value?"
        )
    with chat_col2:
        prod_options = ["(use query)"] + [p['title'] for p in prods]
        prod_choice = st.selectbox("Filter by product (optional)", prod_options, key="prod_filter")

    ask_col1, ask_col2 = st.columns([1, 5])
    with ask_col1:
        ask_btn = st.button("Ask", key="ask_button", use_container_width=True)

    if ask_btn:
        if not user_q or not user_q.strip():
            st.error("Please type a question first.")
        else:
            st.session_state.chat_question = user_q
            try:
                target = None if prod_choice == "(use query)" else prod_choice
                from qa import answer_question
                with st.spinner("Getting answer from AI assistant..."):
                    ans = answer_question(user_q, product_query=target or last_query, top_k=5)
                # append to chat history instead of replacing
                hist = st.session_state.get('chat_history', [])
                hist.append({"q": user_q, "a": ans, "t": time.time()})
                st.session_state['chat_history'] = hist
            except Exception as e:
                st.error(f"QA failed: {str(e)}")
                print(f"[app] QA exception: {e}")

    # render chat history (most recent last)
    if st.session_state.get('chat_history'):
        st.markdown("---")
        st.write("**Chat history**")
        for msg in st.session_state['chat_history']:
            st.markdown(f"**Q:** {msg.get('q')}")
            st.info(msg.get('a'))

# ---------- MAIN: Search button triggers indexing, render always shows results from session -----

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

            # If we got fewer results than requested, try a relaxed search (no site filters)
            if urls and len(urls) < num_results:
                try:
                    more = serp_search(query, num=num_results, site_filters=None)
                    for u in more:
                        if u not in urls:
                            urls.append(u)
                        if len(urls) >= num_results:
                            break
                except Exception:
                    pass

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

                # display cards using augmented JSONs and build comparison table
                products = []
                for i, ppath in enumerate(augmented_paths, start=1):
                    data = load_saved_product(Path(ppath))
                    title = data.get("name") or data.get("title") or "Unknown"
                    price = data.get("offers", {}).get("price") or data.get("price") or "n/a"
                    images = data.get("images") or []
                    img = images[0] if images else None
                    reviews = data.get("reviews") or []
                    url = data.get("source_url") or data.get("url") or ""
                    products.append({
                        "path": str(ppath), "title": title, "price": price,
                        "image": img, "reviews": reviews, "url": url, "orig_pos": i
                    })

                # Attempt to rank by semantic relevance using the indexer
                products_by_stem = {Path(p['path']).stem: p for p in products}
                try:
                    sem = indexer.semantic_search(query, top_k=num_results)
                    ranked = []
                    seen = set()
                    for it in sem:
                        # Since we removed 'ids' from ChromaDB query, try to match by metadata URL
                        meta_url = (it.get('metadata') or {}).get('url')
                        matched = False
                        if meta_url:
                            for s, prod in products_by_stem.items():
                                if prod.get('url') and meta_url in prod.get('url'):
                                    if s not in seen:
                                        ranked.append(prod)
                                        seen.add(s)
                                    matched = True
                                    break
                        # Fallback: if no match by metadata, still count this result
                        if not matched and it.get('document'):
                            # Extract any product match from document text
                            for s, prod in products_by_stem.items():
                                if s not in seen and prod.get('title') and prod['title'] in it.get('document', ''):
                                    ranked.append(prod)
                                    seen.add(s)
                                    matched = True
                                    break
                    
                    # append any products not returned by semantic search
                    for p in products:
                        if Path(p['path']).stem not in seen:
                            ranked.append(p)
                    products_sorted = ranked if ranked else products
                except Exception as e:
                    print(f"[app] semantic search failed: {e}")
                    # fallback to simple heuristic if semantic search fails
                    for p in products:
                        score = 0
                        if p["price"] and str(p["price"]).lower() not in ("n/a", "none", ""):
                            score += 3
                        score += min(len(p.get("reviews") or []), 5)
                        if p.get("image"):
                            score += 1
                        score += max(0, 1.0 - (p.get("orig_pos", 1) - 1) / max(1, len(products))) * 0.5
                        p["score"] = score
                    products_sorted = sorted(products, key=lambda x: x.get("score", 0), reverse=True)

                # Save final product list to session so UI can persist across reruns
                st.session_state['last_products'] = products_sorted
                st.session_state['last_query'] = query
                # clear previous single-answer to avoid confusion
                st.session_state['chat_answer'] = None
                # store a small timestamp
                st.session_state['last_searched_at'] = time.time()

# Always render from session state (persists across reruns, including chatbot asks)
_render_products_and_chat()
