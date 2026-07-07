"""
RagLeap Core — FastAPI web layer
Minimal HTTP interface over the existing CLI pipeline (core.ingest / core.chat).
"""
import os
import shutil
import tempfile
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from core.ingest import ingest_document
from core.chat import ask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ragleap-core.api")

app = FastAPI(
    title="RagLeap Core API",
    description="Minimal self-hosted RAG pipeline — BYOK, no platform fallback keys.",
    version="0.1.0",
)

ALLOWED_EXTENSIONS = {".txt"}


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks_used: int


class UploadResponse(BaseModel):
    document_id: str
    chunks_stored: int


@app.get("/health")
def health():
    return {"status": "ok"}
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks_used: int


class UploadResponse(BaseModel):
    document_id: str
    chunks_stored: int


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Currently supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )
    try:
        raw_bytes = await file.read()
        text = raw_bytes.decode("utf-8")
        result = ingest_document(file.filename, text)
        logger.info("Ingested %s -> %s", file.filename, result)
        return {
            "document_id": result["document_id"],
            "chunks_stored": result["chunks_stored"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Ingestion failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc
    finally:
        await file.close()


@app.post("/chat")
def chat(question: str):
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        result = ask(question)
        return {
            "answer": result["answer"],
            "sources": result.get("sources", []),
            "chunks_used": result.get("chunks_used", 0),
        }
    except Exception as exc:
        logger.exception("Chat failed for question: %s", question)
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc
