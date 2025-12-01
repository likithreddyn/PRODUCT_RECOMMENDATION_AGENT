# src/qa.py
"""
QA module (robust):
- Retrieves top documents from Chroma via indexer_minimal.semantic_search
- Calls Groq chat completions with a safe prompt
- Robustly extracts text from multiple Groq response shapes
- Prints helpful debug info on failure
"""

import os
import traceback
from dotenv import load_dotenv
from textwrap import shorten

# local indexer (the minimal chroma-based indexer you already ran)
# ensure file is src/indexer_minimal.py or adjust import accordingly
from indexer_minimal import semantic_search

# Groq client
try:
    from groq import Groq
except Exception as e:
    raise RuntimeError("Missing dependency: install the 'groq' package in your venv.") from e

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found in .env. Add your Groq secret key (gsk_...) to .env")

client = Groq(api_key=GROQ_API_KEY)

# IMPORTANT: replace this with the exact model id you validated in the Groq Playground
# Example values you might use: "llama-4-maverick", "llama3-8b-8192", "llama3-70b-8192"
GROQ_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"


def extract_text_from_groq_response(resp):
    """
    Robust extractor for Groq Chat Completion responses.
    Handles multiple shapes returned by different SDK versions:
     - resp.choices[0].message being dict-like or object with .content
     - resp.choices[0].text
     - older/newer variations
    Returns extracted string.
    """
    if resp is None:
        raise ValueError("Empty response from Groq")

    # try to access choices in various ways
    choices = None
    # resp may be an object with attribute 'choices'
    if hasattr(resp, "choices"):
        try:
            choices = resp.choices
        except Exception:
            choices = None

    # resp may be a dict-like
    if choices is None and isinstance(resp, dict):
        choices = resp.get("choices")

    if not choices:
        raise ValueError("No 'choices' found in Groq response")

    if len(choices) == 0:
        raise ValueError("Empty choices list in Groq response")

    choice0 = choices[0]

    # Try different ways to extract a message/content
    # 1) choice0.message -> object or dict
    msg = None
    if hasattr(choice0, "message"):
        msg = choice0.message
    elif isinstance(choice0, dict) and "message" in choice0:
        msg = choice0["message"]

    # 2) sometimes content is directly on choice0 as 'text' or 'content'
    if msg is None:
        if hasattr(choice0, "text"):
            return str(choice0.text)
        if isinstance(choice0, dict) and "text" in choice0:
            return str(choice0["text"])
        if isinstance(choice0, dict) and "content" in choice0:
            return str(choice0["content"])

    # now msg may be object or dict
    # if it's a dict
    if isinstance(msg, dict):
        # typical case: {'role': 'assistant', 'content': '...'}
        if "content" in msg:
            c = msg["content"]
            # sometimes content is dict-like { 'text': '...' }
            if isinstance(c, dict) and "text" in c:
                return str(c["text"])
            return str(c)
        if "text" in msg:
            return str(msg["text"])

    # if msg is an object with attributes
    try:
        # attribute .content
        if hasattr(msg, "content"):
            content = getattr(msg, "content")
            if isinstance(content, str):
                return content
            if isinstance(content, dict) and "text" in content:
                return str(content["text"])
        # attribute .get (dict-like)
        if hasattr(msg, "get") and callable(getattr(msg, "get")):
            c = msg.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, dict) and "text" in c:
                return str(c["text"])
    except Exception:
        pass

    # Last resort: stringify the message object
    try:
        return str(msg)
    except Exception as e:
        raise ValueError("Could not extract text from Groq response") from e


def build_system_prompt():
    return (
        "You are a concise, honest product assistant who replies like a helpful friend. "
        "When given product evidence (title, description, price, and a few reviews), "
        "answer the user's question directly in 2-4 sentences, include 1 short pro and 1 short con if applicable, "
        "and mention the source URL at the end."
    )


def make_evidence_block(items):
    """
    items: list of {'document','metadata','distance'}
    Keep each doc short to avoid extremely long contexts.
    """
    blocks = []
    for i, it in enumerate(items, start=1):
        title = it["metadata"].get("title", "") if it.get("metadata") else ""
        url = it["metadata"].get("url", "") if it.get("metadata") else ""
        doc = it.get("document", "")
        doc_snippet = shorten(doc, width=800, placeholder=" ...")
        blocks.append(f"PRODUCT {i}:\nTITLE: {title}\n{doc_snippet}\nURL: {url}\n")
    return "\n---\n".join(blocks)


def answer_question(question: str, product_query: str = None, top_k: int = 3):
    """
    product_query is used to retrieve products from the index (semantic search).
    If not provided, the system uses the natural question as a fallback query.
    """
    try:
        if not product_query:
            product_query = question

        items = semantic_search(product_query, top_k=top_k)
        if not items:
            return "I couldn't find product data to answer that — try rephrasing or index more products."

        evidence = make_evidence_block(items)
        system = build_system_prompt()

        user_prompt = (
            f"User question: {question}\n\n"
            f"Use the following product evidence (do not invent facts):\n{evidence}\n\n"
            "Answer concisely and truthfully."
        )

        # call Groq chat completion
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=250,
            temperature=0.1
        )

        # robustly extract text
        try:
            text = extract_text_from_groq_response(resp)
            return text.strip()
        except Exception as ex:
            # Debug: print raw response for inspection
            print("DEBUG: failed to extract text. Raw response object (repr):")
            try:
                print(repr(resp))
            except Exception:
                pass
            # re-raise to surface error to caller or return a friendly message
            traceback.print_exc()
            return f"Sorry — I couldn't extract the model response due to: {ex}"

    except Exception as e:
        traceback.print_exc()
        return f"Sorry — I couldn't get an answer due to an internal error: {e}"


if __name__ == "__main__":
    # quick interactive test — change product_query to match one of your indexed products
    q = "Is this LEGO set worth the price, or are there better alternatives under ₹600?"
    print("Running QA test. This may take a few seconds...")
    out = answer_question(q, product_query="LEGO Minifigures Spider-Man", top_k=3)
    print("\n--- ANSWER ---\n")
    print(out)
