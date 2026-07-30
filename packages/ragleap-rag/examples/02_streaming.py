"""
ragleap-rag — Streaming responses.

Use ask_stream() instead of ask() to get the answer as it's generated,
token-by-token, instead of waiting for the full response — useful for
chat UIs where you want to show text appearing progressively.

Run:
    python 02_streaming.py
"""
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

GEMINI_API_KEY = "your-gemini-api-key-here"
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

rag = RagLeap(
    database_url=DATABASE_URL,
    embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key=GEMINI_API_KEY),
    primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key=GEMINI_API_KEY),
)
rag.init_schema()

rag.ingest_text(
    filename="product_faq.txt",
    text="Our product supports Python, JavaScript, and Go SDKs. "
         "Enterprise customers get dedicated support with a 1-hour SLA.",
)

print("Question: What SDKs are supported?")
print("Answer: ", end="", flush=True)
for piece in rag.ask_stream("What SDKs are supported?"):
    print(piece, end="", flush=True)
print()
