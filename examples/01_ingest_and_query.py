"""
Example: Ingest a document and ask a question about it.

Prerequisites:
  - RagLeap Core running locally (docker compose up --build -d)
  - A .txt, .pdf, or .docx file to test with

Usage:
    python examples/01_ingest_and_query.py path/to/document.txt "Your question here"
"""
import sys
import requests

API_URL = "http://localhost:8000"


def ingest_document(filepath: str) -> dict:
    """Upload a document to RagLeap Core for ingestion."""
    with open(filepath, "rb") as f:
        response = requests.post(f"{API_URL}/upload", files={"file": f})
    response.raise_for_status()
    return response.json()


def ask_question(question: str) -> dict:
    """Ask a question and get a cited answer from ingested documents."""
    response = requests.post(f"{API_URL}/chat", params={"question": question})
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python examples/01_ingest_and_query.py <filepath> <question>")
        sys.exit(1)

    filepath, question = sys.argv[1], sys.argv[2]

    print(f"Ingesting {filepath}...")
    result = ingest_document(filepath)
    print(f"✅ Ingested: {result['chunks_stored']} chunks stored (document_id={result['document_id']})\n")

    print(f"Asking: {question}")
    answer = ask_question(question)
    print(f"\n Answer: {answer['answer']}")
    print(f" Sources: {answer['sources']}")
