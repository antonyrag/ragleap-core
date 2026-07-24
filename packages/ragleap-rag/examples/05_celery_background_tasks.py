"""
ragleap-rag — Background ingestion and asking with Celery.

The constraint that matters here: RagLeap's connection pool is created
per-instance and is NOT fork-safe or shareable across processes. If you
create one global RagLeap object and Celery forks worker processes from
it (the default "prefork" pool), every forked worker inherits the same
pool object and file descriptors — this breaks in ways that are easy to
misdiagnose (hung queries, connection errors under load, or workers that
seem fine until concurrent tasks land).

The fix: each worker process creates its OWN RagLeap instance, once,
via Celery's worker_process_init signal — not at module import time.

Setup:
    pip install ragleap-rag celery redis
    # or: uv add ragleap-rag celery redis

    You'll need:
    1. A PostgreSQL database with pgvector (see 01_basic_ingest_and_ask.py)
    2. Redis running locally, used here as both the Celery broker and
       result backend: docker run -d -p 6379:6379 redis:7
    3. A free Gemini API key: https://aistudio.google.com/apikey

Run:
    # Terminal 1 — start a worker:
    celery -A 05_celery_background_tasks worker --loglevel=info

    # Terminal 2 — enqueue tasks:
    python 05_celery_background_tasks.py
"""
from celery import Celery
from celery.signals import worker_process_init
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

GEMINI_API_KEY = "your-gemini-api-key-here"
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
REDIS_URL = "redis://localhost:6379/0"

app = Celery("ragleap_tasks", broker=REDIS_URL, backend=REDIS_URL)

# WRONG — do not do this:
#   rag = RagLeap(database_url=DATABASE_URL, ...)   # created at import time
#   @app.task
#   def ingest_task(text): rag.ingest_text(...)     # every forked worker
#                                                     # shares this one pool
#
# Every worker process gets its own RagLeap instance instead, built lazily
# the first time a task in that process needs it.

_rag_instance = None


def get_rag() -> RagLeap:
    """Return this worker process's own RagLeap instance, creating it once."""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RagLeap(
            database_url=DATABASE_URL,
            embedder=EmbeddingConfig(provider="gemini", api_key=GEMINI_API_KEY),
            primary=ProviderConfig(provider="gemini", api_key=GEMINI_API_KEY),
            # Redis-backed cache is a *separate* concern from the Celery
            # broker above — same Redis server is fine, different db index
            # keeps them from colliding.
            cache_backend="redis",
            redis_url="redis://localhost:6379/1",
        )
        _rag_instance.init_schema()
    return _rag_instance


@worker_process_init.connect
def init_worker(**kwargs):
    """Build this worker's RagLeap instance right after the process forks,
    not before — this is what makes the pool safe per-process."""
    get_rag()


@app.task(name="ragleap.ingest_text")
def ingest_text_task(filename: str, text: str, metadata: dict | None = None):
    rag = get_rag()
    result = rag.ingest_text(filename=filename, text=text, metadata=metadata)
    return {"document_id": result.document_id, "chunks_stored": result.chunks_stored}


@app.task(name="ragleap.ask")
def ask_task(query: str, session_id: str | None = None):
    rag = get_rag()
    answer = rag.ask(query, session_id=session_id)
    return {
        "answer": answer["answer"],
        "sources": answer["sources"],
        "provider_used": answer["provider_used"],
    }


if __name__ == "__main__":
    # Enqueue a couple of tasks — run this while a worker (see docstring) is up.
    r1 = ingest_text_task.delay(
        filename="company_handbook.txt",
        text="Our company offers unlimited PTO, a fully remote work policy, "
             "and a $500/year learning budget for courses and books.",
    )
    print("Enqueued ingest task:", r1.id)
    print("Result (blocks until worker finishes):", r1.get(timeout=30))

    r2 = ask_task.delay("How much PTO do employees get?")
    print("Enqueued ask task:", r2.id)
    print("Result:", r2.get(timeout=30))
