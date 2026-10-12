import os
import re #used for pattern matching
import json #used to return data from llm 
from typing import Any #used in validation

from dotenv import load_dotenv #imports fast api and url from evn file - supabase ai 
from fastapi import FastAPI, Query, HTTPException #backend framework - fastapi ,exceptions and errors
from fastapi.responses import FileResponse#used for html file 
from fastapi.staticfiles import StaticFiles #connects backend and frontend 
from fastapi.middleware.cors import CORSMiddleware #allows communication btwn frontend and backend 
from pydantic import BaseModel #used to define model for product 
from supabase import create_client #used to insert and read data in the db
from openai import OpenAI #connects to llm for parsing 
import spacy #nlp library for tokenisation 

# ---------------- Setup ----------------
load_dotenv()
SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY = (#using the supabase and openai api keys to access the files
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
    os.getenv("OPENAI_API_KEY"),
)
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "products")#accesses the products table which containes product discription 
if not all([SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY]):
    raise RuntimeError("Missing env vars")#checks if all the 3 keys are present else does not connect 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)#connects to cloud databse 
client = OpenAI(api_key=OPENAI_API_KEY)#connects to gpt model 
app = FastAPI(title="AI E-commerce Agent")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")#allows frontend to call backend apis 

nlp = spacy.load("en_core_web_sm")#loads nlp model for tokenisation and analysis of language
GENERIC_STOPWORDS = {#defines words to be ignored 
    "need", "want", "looking", "look", "gift", "present", "buy", "for", "with",
    "something", "item", "please",  "surprise",
}
NON_PRODUCT_TOKENS = {#ignore 
    "mom", "mother", "dad", "father", "friend", "sister", "brother", "wife", "husband",
    "birthday", "anniversary", "farewell", "gift", "present", "her", "him", "their",
}

class Product(BaseModel):#checks the structure of the data - should have all 3 components or the data is ignored
    name: str
    description: str
    price: float

def products_table():#helps access supabase table 
    return supabase.table(SUPABASE_TABLE)


# ---------------- Basic Endpoints ----------------
@app.get("/")
def root():
    return FileResponse("frontend/index.html") #connects backend api with frontend interface


@app.get("/products")#fetches all product in the cloud db 
def get_products():
    try:
        return products_table().select("*").execute().data#select all data
    except Exception as exc:#if not then exceptions error 
        raise HTTPException(status_code=500, detail=f"Supabase read failed for table '{SUPABASE_TABLE}': {exc}")


@app.post("/products")#used to add new product to the table
def add_product(product: Product):
    try:
        return products_table().insert(product.model_dump()).execute().data#.dump - helps convert it to dictionary format
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Supabase insert failed for table '{SUPABASE_TABLE}': {exc}")

#confirms the health ie chk if the databse is connected by extracting 1 element 
@app.get("/health")
def health() -> dict[str, Any]:
    try:
        products_table().select("*").limit(1).execute()
        db_ok = True
        error = None
    except Exception as exc:
        db_ok = False
        error = str(exc)
    return {
        "ok": db_ok,
        "supabase_url_set": bool(SUPABASE_URL),
        "supabase_table": SUPABASE_TABLE,
        "error": error,
    }


# ---------------- Helpers ----------------
def extract_price(q: str):#used to extract price checks for number in the range 2 digit to 6 digit and stores the value as price 
    m = re.search(r"\b\d{2,6}\b", q)
    return int(m.group()) if m else None


def rule_based(q: str):
    query_lower = q.lower()#coverts to lower case 
    doc = nlp(q)#passes through nlp model to convert into tokens 
    nouns = [t.lemma_.lower() for t in doc if t.pos_ in {"NOUN", "PROPN"} and len(t.lemma_) > 2]#helps ectract nouns  ------ product main description
    restrictions = []#lemma ensures shoes and shoe is treated as one so singular or plural does not matter 
    if "diabetic" in query_lower or "sugar" in query_lower:
        restrictions.append("sugar-free")
    if "gluten" in query_lower:
        restrictions.append("gluten-free")
    if "allergic" in query_lower or "allergy" in query_lower:
        match = re.search(r"(allergic to|allergy to|avoid)\s+([a-z\s]+)", query_lower)
        if match:
            allergen = match.group(2).strip().replace(" ", "-")
            restrictions.append(f"{allergen}-free")
    return {#create the format needed - category - price and restriction
        "category": sorted(set(nouns)) or [],
        "price": extract_price(q),
        "restrictions": restrictions,
    }


def llm_simplify_query(q: str) -> str:#summarises the query entered by the user where q is the user query 
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[#sets rukes for the gpt model to include product budget restriction
            {
                "role": "system",
                "content": (
                    "Rewrite user shopping requests into one concise query containing "
                    "product intent, budget, and restrictions (if any). Return plain text only."
                ),
            },
            {"role": "user", "content": q},
        ],
    )
    return (resp.choices[0].message.content or q).strip()#takes the first ans given by the llm 


def llm_interpret(q: str):#converts user query to json format 
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Return JSON with category (array), brand, price, restrictions (array), suggestions."
                ),
            },
            {"role": "user", "content": q},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content or "{}")#take first choice by llm 


def make_response(filters, results):#compares the json query with the supabase description 
    parts = ["Got it! You can try "]
    if filters.get("category"):
       parts.append(", ".join(filters["category"]))
    
    if filters.get("restrictions"):
        parts.append(f"that are {', '.join(filters['restrictions'])}")
    if filters.get("price"):
        parts.append(f"within ₹{filters['price']}")
    msg = " ".join(parts) + "."
    if results:
        msg += " Options: " + "; ".join(f"{r['name']} — ₹{r['price']}" for r in results)
    else:
        msg += " No exact matches, but here are alternatives."
    return msg


def relaxed_ranked_search(query_text: str, limit: int = 5):#returns the product names whose tokens have matched
    """Generalized fallback: rank DB products by meaningful token overlap."""
    def extract_tokens(text: str) -> list[str]:#breaks user query to tokens and lemmatizes it 
        doc = nlp(text.lower())
        tokens: list[str] = []
        for token in doc:
            lemma = token.lemma_.strip().lower()
            if (
                token.is_stop
                or not token.is_alpha
                or len(lemma) < 3
                or lemma in GENERIC_STOPWORDS
                or lemma in NON_PRODUCT_TOKENS
            ):
                continue
            if token.pos_ in {"NOUN", "PROPN", "ADJ"}:#join accept 
                tokens.append(lemma)
        return list(dict.fromkeys(tokens))

    rows = products_table().select("*").limit(200).execute().data or []
    query_tokens = extract_tokens(query_text)
    if not query_tokens:
        query_tokens = [
            t for t in re.findall(r"[a-zA-Z]{3,}", query_text.lower())
            if t not in GENERIC_STOPWORDS and t not in NON_PRODUCT_TOKENS
        ][:5]
    scored = []
    for row in rows:
        name = str(row.get("name", "")).lower()
        desc = str(row.get("description", "")).lower()
        score = 0
        matched = 0
        for token in query_tokens:#compare query token and supabase product 
            in_name = token in name
            in_desc = token in desc
            if in_name or in_desc:
                matched += 1
                score += 3 if in_name else 1
        if matched > 0:
            scored.append((score, matched, row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)#stores matche dproducts with decending order of number of match count
    return [row for _, _, row in scored[:limit]]


# ---------------- NLP Search ----------------
@app.get("/nlp_search")#takes user query and give uotput of possible products 
def nlp_search(query: str = Query(...)):
    simplified_query = query
    try:
        simplified_query = llm_simplify_query(query)#tries to simplify the query 
    except Exception:
        simplified_query = query

    try:#simplified query is interpreted-----converted to json format
        filters, source = llm_interpret(simplified_query), "LLM"
    except Exception:
        filters, source = rule_based(query), "rules"

    categories = filters.get("category") or []
    if isinstance(categories, str):
        categories = [categories]
    filters["category"] = [
        str(c).lower()
        for c in categories
        if str(c).strip() and str(c).lower() not in NON_PRODUCT_TOKENS
    ]

    rows = products_table().select("*").limit(500).execute().data or []
    results = []
    for row in rows:
        name = str(row.get("name", "")).lower()
        desc = str(row.get("description", "")).lower()

        category_terms = filters.get("category") or []#compares db category and json category 
        category_ok = True
        if category_terms:
            category_ok = any(term in name or term in desc for term in category_terms)

        restriction_ok = True
        for restriction in filters.get("restrictions") or []:#matching the restriction 
            keyword = str(restriction).replace("-free", "")
            if restriction not in desc and keyword not in desc:
                restriction_ok = False
                break

        price_ok = True #checking price constriant 
        if filters.get("price"):
            try:
                price_ok = float(row.get("price", 0)) < float(filters["price"])
            except Exception:
                price_ok = True

        if category_ok and restriction_ok and price_ok:#if all true accept 
            results.append(row)

    results = sorted(results, key=lambda r: float(r.get("price", 0)))[:5]#lowest price first 
    query_tokens = [t for t in re.findall(r"[a-zA-Z]{3,}", simplified_query.lower()) if t not in GENERIC_STOPWORDS]

    # Check DB availability for extracted requirement; if no exact hit, use generalized ranked search.
    in_database = len(results) > 0
    if not in_database or (query_tokens and len(results) > 0):#checks ranks based on number of tokens matched 
        fallback_results = relaxed_ranked_search(simplified_query, limit=5)
        if fallback_results:
            results = fallback_results

    return {
        "query": query,
        "simplified_query": simplified_query,
        "source": source,
        "llm_output": filters,
        "results": results,
        "in_database": in_database,
        "conversation_output": make_response(filters, results),
    }
