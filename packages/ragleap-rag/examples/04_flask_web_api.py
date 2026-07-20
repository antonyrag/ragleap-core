"""
ragleap-rag — Drop-in Flask web API.

A minimal, copy-paste-ready web server exposing /ingest and /ask
endpoints — the fastest way to turn ragleap-rag into a working web
service. For an async/production setup, the same RagLeap object works
identically inside FastAPI (just swap Flask's request handling for
FastAPI's, the rag.* calls don't change at all).

Setup:
    pip install ragleap-rag flask

Run:
    python 04_flask_web_api.py
    # then, in another terminal:
    curl -X POST http://localhost:5000/ingest -F "file=@yourdoc.txt"
    curl -X POST "http://localhost:5000/ask?question=your+question+here"
"""
from flask import Flask, request, jsonify
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig

GEMINI_API_KEY = "your-gemini-api-key-here"
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

app = Flask(__name__)

rag = RagLeap(
    database_url=DATABASE_URL,
    embedder=EmbeddingConfig(provider="gemini", api_key=GEMINI_API_KEY),
    primary=ProviderConfig(provider="gemini", api_key=GEMINI_API_KEY),
)
rag.init_schema()


@app.route("/ingest", methods=["POST"])
def ingest():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400
    try:
        result = rag.ingest(file.filename, file.read())
        return jsonify({"document_id": result.document_id, "chunks_stored": result.chunks_stored})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ask", methods=["POST"])
def ask():
    question = request.args.get("question", "")
    if not question.strip():
        return jsonify({"error": "Question cannot be empty"}), 400
    try:
        answer = rag.ask(question)
        return jsonify(answer)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
