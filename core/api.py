"""
RagLeap Core — FastAPI web layer
Minimal HTTP interface over the existing CLI pipeline (core.ingest / core.chat).
"""
import os
import shutil
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response
from pydantic import BaseModel

from core.ingest import ingest_document
from core.parsers import extract_text
from core.chat import ask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ragleap-core.api")

app = FastAPI(
    title="RagLeap Core API",
    description="Minimal self-hosted RAG pipeline — BYOK, no platform fallback keys.",
    version="0.1.0",
)

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_QUESTION_LENGTH = 2000


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

        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({len(raw_bytes) / 1024 / 1024:.1f} MB). Max size is {MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f} MB.",
            )

        text = extract_text(file.filename, raw_bytes)
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
    if len(question) > MAX_QUESTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long ({len(question)} chars). Max is {MAX_QUESTION_LENGTH} chars.",
        )
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


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Twilio-compatible WhatsApp webhook. Twilio sends form-encoded POST data
    (not JSON), with fields like 'Body' (message text) and 'From'
    (sender's phone, prefixed 'whatsapp:').
    """
    from channels.whatsapp.router import handle_incoming_message, _verify_twilio_signature

    form = await request.form()
    params = dict(form)

    incoming_msg = params.get("Body", "")
    from_phone = params.get("From", "")
    if from_phone.startswith("whatsapp:"):
        from_phone = from_phone.replace("whatsapp:", "")

    if not incoming_msg or not from_phone:
        raise HTTPException(status_code=400, detail="Missing Body or From field.")

    signature = request.headers.get("x-twilio-signature", "")
    if signature:
        url = str(request.url)
        if not _verify_twilio_signature(url, params, signature):
            logger.warning("WhatsApp webhook: invalid Twilio signature")
            raise HTTPException(status_code=403, detail="Invalid signature.")

    logger.info(f"WhatsApp webhook: message from {from_phone}: {incoming_msg[:50]}")
    handle_incoming_message(from_phone, incoming_msg)

    # Twilio expects a TwiML (XML) response, even if empty — we already
    # sent the reply via the Twilio API directly in handle_incoming_message.
    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
