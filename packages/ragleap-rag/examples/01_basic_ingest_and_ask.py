"""
ragleap-rag — Basic usage: ingest a document, ask a question.

Setup:
    pip install ragleap-rag
    # or: uv add ragleap-rag

    You'll need:
    1. A PostgreSQL database with the pgvector extension available.
       Easiest way locally: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg16
    2. A free Gemini API key: https://aistudio.google.com/apikey

Run:
    python 01_basic_ingest_and_ask.py
"""
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

GEMINI_API_KEY = "your-gemini-api-key-here"
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

rag = RagLeap(
    database_url=DATABASE_URL,
    embedder=EmbeddingConfig(provider="gemini", api_key=GEMINI_API_KEY),
    primary=ProviderConfig(provider="gemini", api_key=GEMINI_API_KEY),
)

# One-time setup — creates the required tables/indexes if they don't exist.
# Safe to call every run; it's idempotent.
rag.init_schema()

# Ingest some text directly (use rag.ingest(filename, raw_bytes) instead
# if you have a .txt/.pdf/.docx file to read from disk).
result = rag.ingest_text(
    filename="company_handbook.txt",
    text="Our company offers unlimited PTO, a fully remote work policy, "
         "and a $500/year learning budget for courses and books.",
)
print(f"Ingested document {result.document_id} ({result.chunks_stored} chunks)")

# Ask a question grounded in what you just ingested.
answer = rag.ask("How much PTO do employees get?")
print("\nAnswer:", answer["answer"])
print("Sources:", answer["sources"])
print("Provider used:", answer["provider_used"])
print("Token usage:", answer["usage"])
