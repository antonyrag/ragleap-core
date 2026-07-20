"""
ragleap-rag — Provider fallback and hybrid search control.

Shows two production-relevant features:
1. Configuring a fallback provider chain — if your primary LLM fails
   (rate limit, outage, bad key), it automatically retries with the
   next provider in the list.
2. Toggling hybrid=False to use dense-only (vector) retrieval instead
   of the default hybrid (dense+sparse) search — cheaper, one query
   instead of two, useful if your content doesn't benefit from
   keyword/exact-match search.

Run:
    python 03_fallback_and_hybrid_search.py
"""
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

GEMINI_API_KEY = "your-gemini-api-key-here"
GROQ_API_KEY = "your-groq-api-key-here"  # free tier: https://console.groq.com
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

rag = RagLeap(
    database_url=DATABASE_URL,
    embedder=EmbeddingConfig(provider="gemini", api_key=GEMINI_API_KEY),
    primary=ProviderConfig(provider="gemini", api_key=GEMINI_API_KEY),
    fallbacks=[
        ProviderConfig(provider="groq", api_key=GROQ_API_KEY, model="llama-3.3-70b-versatile"),
    ],
)
rag.init_schema()

rag.ingest_text(
    filename="internal_wiki.txt",
    text="Our internal error code E4402 means a rate limit was hit on "
         "the payments service. Retry after 30 seconds with exponential backoff.",
)

# Default: hybrid dense+sparse retrieval (recommended for most use cases)
answer = rag.ask("What does error E4402 mean?")
print("Hybrid search answer:", answer["answer"])
print("Provider used:", answer["provider_used"])  # 'gemini' unless it failed, then 'groq'

# Dense-only retrieval (cheaper, one query instead of two)
answer_dense = rag.ask("What does error E4402 mean?", hybrid=False)
print("\nDense-only answer:", answer_dense["answer"])
