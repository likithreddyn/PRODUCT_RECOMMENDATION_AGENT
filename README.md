Here is a **clean, professional, beautifully formatted Markdown version** of your README section.
I fixed spacing, alignment, bullet structure, and visuals while keeping everything elegant and GitHub-friendly.

---

# 📦 Product Recommendation Agent

### **AI-powered shopping assistant with live product search, web scraping, semantic indexing, and LLM-driven answers**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red?style=for-the-badge)
![Groq](https://img.shields.io/badge/Groq-LLM-orange?style=for-the-badge)
![SerpAPI](https://img.shields.io/badge/SerpAPI-Search-green?style=for-the-badge)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Semantic%20Search-yellow?style=for-the-badge)

---

## 🚀 Overview

The **Product Recommendation Agent** is an intelligent shopping assistant that:

* ✔ Searches **Amazon, Flipkart, Nykaa**, and other e-commerce sites in real time using **SerpAPI**
* ✔ Fetches each product page and extracts **Title, Price, Images, Description & Reviews**
* ✔ Normalizes and stores product data into structured JSON
* ✔ Creates a **semantic vector index** using ChromaDB
* ✔ Lets users ask questions and receive **accurate, evidence-backed answers**
* ✔ Uses **Groq’s ultra-fast LLM** to answer like a **helpful friend**
* ✔ Displays beautiful product cards in a clean Streamlit UI

This project demonstrates end-to-end agent architecture:
**search → extraction → indexing → retrieval → LLM reasoning → user interaction**

---

## 🎯 Features

### 🔍 1. Live Product Scouting

* Uses SerpAPI to search the web
* Filters results to trusted e-commerce domains
* Fetches real product pages for authentic data

### 🧠 2. AI-Powered Product Q&A

Ask anything like:

> *“Is this good for kids?”*
> *“Is the material durable?”*
> *“What is the exact price?”*

The system analyzes product evidence and responds truthfully.

### 📝 3. Smart Web Scraper & Parser

* Extracts JSON-LD
* Falls back to HTML parsing when needed
* Captures reviews, product details & images
* Includes a **price accuracy engine** for reliable pricing

### 🔎 4. Semantic Search with ChromaDB

Every product is embedded using **SentenceTransformers** and stored in ChromaDB:

* Relevance-based retrieval
* Similar product matching
* Accurate LLM context

### 🖼 5. Streamlit Frontend

* Clean, responsive UI
* Product cards with image + verified price
* “Ask a Question” section
* Background auto-indexing

---

## 🗂️ Project Structure

```
product_recommendation_agent/
│
├── src/
│   ├── app.py                 # Streamlit UI
│   ├── serp_search.py         # Web search via SerpAPI
│   ├── parser.py              # HTML fetch + product extraction
│   ├── fetcher.py             # Helper for parsing
│   ├── indexer_minimal.py     # ChromaDB embedding & indexing
│   └── qa.py                  # Groq LLM Q&A engine
│                    
│
├── data/
│   ├── pages/                 # Raw HTML pages (auto-filled)
│   ├── products/              # Normalized JSON files
│   └── chroma_db/             # Vector index storage
│
├── .env                       # API keys (deployment only)
│             
│
├── requirements.txt
└── README.md

```

---

## ⚙️ Installation & Running Locally

### **1. Clone the repo**

```bash
git clone https://github.com/<your-name>/PRODUCT_RECOMMENDATION_AGENT
cd PRODUCT_RECOMMENDATION_AGENT
```

### **2. Create virtual environment**

```bash
python -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
```

### **3. Install dependencies**

```bash
pip install -r requirements.txt
```

### **4. Create a `.env` file**

```
GROQ_API_KEY = "your_groq_key"
SERPAPI_KEY = "your_serpapi_key"
```

### **5. Run the app**

```bash
streamlit run src/app.py
```

---

## 🌐 Deployment (Streamlit Cloud)

1. Push your project to GitHub
2. Go to **share.streamlit.io/deploy**
3. Paste your repository URL
4. Set `Main file path` → `src/app.py`
5. Add secrets under **Advanced → Secrets**:

```toml
GROQ_API_KEY = "xxxxx"
SERPAPI_KEY = "xxxxx"
```

6. Click **Deploy** 🎉

---

## 🧠 Tech Stack

| Component    | Technology                                    |
| ------------ | --------------------------------------------- |
| UI           | **Streamlit**                                 |
| LLM          | **Groq (LLaMA 3, Maverick, etc.)**            |
| Search       | **SerpAPI**                                   |
| Scraping     | **Requests + BeautifulSoup + Custom Parsers** |
| Embeddings   | **SentenceTransformers (all-MiniLM-L6-v2)**   |
| Vector Store | **ChromaDB**                                  |
| Backend      | Python                                        |
| Deployment   | Streamlit Cloud                               |

---

## 🧪 Example: What the Agent Can Do

**User question:**
*“Is this headphone good for gym use and how long does the battery last?”*

**The agent responds:**

* Gives a **short, accurate explanation**
* Adds **1 pro and 1 con**
* Mentions **real verified price**
* Provides **source URL**
* Uses **real evidence**, not hallucinations

---


## 🎉 Why This Project is Special

This is not just a chatbot — it's a **full-fledged AI Agent** that:

* ✔ Searches the **live internet**
* ✔ Extracts **authentic product data**
* ✔ Builds a **semantic vector index**
* ✔ Understands **context**
* ✔ Answers with **grounded, source-backed facts**

---

It demonstrates advanced skills in:

* AI agent design
* Web information extraction
* Vector search
* LLM integration
* Streamlit deployment
* Full-stack AI development

---
