"""
RagLeap Core — FastAPI web layer
Minimal HTTP interface over the existing CLI pipeline (core.ingest / core.chat).
"""
import os
import shutil
import logging

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.ingest import ingest_document
from core.parsers import extract_text
from core.chat import ask, ask_stream
from core.integrations import service as integrations_service
from core.integrations.factory import get_connector
from core.employees import profile as employee_profile
from core.employees import roles as employee_roles
from core.employees import skills as employee_skills
from core.employees import learning as employee_learning
from core import workflows

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


class ProfileUpdateRequest(BaseModel):
    business_name: str | None = None
    industry: str | None = None
    description: str | None = None
    products_services: str | None = None
    target_customers: str | None = None
    working_hours: str | None = None
    location: str | None = None
    tone_preference: str | None = None
    primary_language: str | None = None
    owner_instructions: str | None = None


class WorkflowCreateRequest(BaseModel):
    name: str
    webhook_url: str
    description: str = ""
    channels: list[str] = []
    is_active: bool = False


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    webhook_url: str | None = None
    channels: list[str] | None = None
    is_active: bool | None = None


class RoleUpdateRequest(BaseModel):
    display_name: str | None = None
    channels: list[str] | None = None
    skill_tags: list[str] | None = None
    personality: str | None = None
    is_active: bool | None = None


class DataSourceCreateRequest(BaseModel):
    name: str
    source_type: str
    connection_string: str | None = None
    api_endpoint: str | None = None
    api_key: str | None = None
    api_headers: dict = {}
    query_template: str | None = None
    field_mappings: dict = {}
    user_identifier_field: str = "user_id"


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


def _validate_question(question: str):
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Question too long ({len(question)} chars). Max is {MAX_QUESTION_LENGTH} chars.",
        )


@app.post("/chat")
def chat(
    question: str,
    top_k: int = 5,
    temperature: float | None = None,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
    hybrid: bool = True,
    role: str | None = None,
):
    """
    Ask a question grounded in previously ingested documents.

    top_k: number of chunks to retrieve and ground the answer in.
    temperature: LLM sampling temperature (lower = more deterministic/faithful
        to context; default comes from DEFAULT_TEMPERATURE in .env, 0.3).
    system_prompt: override the default grounded-QA instructions.
    max_tokens: override the default max output length.
    hybrid: use dense+sparse fused retrieval (default True) vs. dense-only.
    """
    _validate_question(question)
    try:
        result = ask(
            question, top_k=top_k, temperature=temperature,
            system_prompt=system_prompt, max_tokens=max_tokens, hybrid=hybrid,
            role=role,
        )
        return {
            "answer": result["answer"],
            "sources": result.get("sources", []),
            "chunks_used": result.get("chunks_used", 0),
            "chunks_sent": result.get("chunks_sent"),
            "detected_language": result.get("detected_language"),
            "provider_used": result.get("provider_used"),
            "usage": result.get("usage"),
        }
    except Exception as exc:
        logger.exception("Chat failed for question: %s", question)
        raise HTTPException(status_code=500, detail=f"Chat failed: {exc}") from exc


@app.post("/chat/stream")
def chat_stream(
    question: str,
    top_k: int = 5,
    temperature: float | None = None,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
    hybrid: bool = True,
    role: str | None = None,
):
    """
    Same as /chat, but streams the answer text back as it's generated
    (text/plain, chunked transfer) instead of waiting for the full
    response. Sources/chunks_used/detected_language aren't available in
    a streaming response — use /chat if you need those.
    """
    _validate_question(question)

    def _generate():
        try:
            for piece in ask_stream(
                question, top_k=top_k, temperature=temperature,
                system_prompt=system_prompt, max_tokens=max_tokens, hybrid=hybrid,
                role=role,
            ):
                yield piece
        except Exception as exc:
            logger.exception("Streaming chat failed for question: %s", question)
            yield f"\n[Error: {exc}]"

    return StreamingResponse(_generate(), media_type="text/plain")


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


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram webhook. Telegram sends JSON payloads with an 'update' object
    containing 'message' -> 'chat' -> 'id' and 'message' -> 'text'.
    """
    from channels.telegram.router import handle_incoming_message, _verify_webhook_secret

    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not _verify_webhook_secret(secret):
        logger.warning("Telegram webhook: invalid secret token")
        raise HTTPException(status_code=403, detail="Invalid secret token.")

    update = await request.json()
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        # Not a text message we handle (could be a different update type) — acknowledge anyway.
        return {"ok": True}

    logger.info(f"Telegram webhook: message from chat {chat_id}: {text[:50]}")
    handle_incoming_message(chat_id, text)

    return {"ok": True}


@app.post("/webhook/discord")
async def discord_webhook(request: Request):
    """
    Discord webhook. Handles both the PING verification challenge Discord
    sends when registering the endpoint, and real MESSAGE_CREATE-style
    interaction payloads.
    """
    from channels.discord.router import handle_incoming_message, verify_discord_signature

    signature = request.headers.get("x-signature-ed25519", "")
    timestamp = request.headers.get("x-signature-timestamp", "")
    body = await request.body()

    if not verify_discord_signature(signature, timestamp, body):
        logger.warning("Discord webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid request signature.")

    data = await request.json()

    # Discord's PING verification challenge — must respond with type: 1
    if data.get("type") == 1:
        return {"type": 1}

    channel_id = data.get("channel_id")
    content = data.get("content", "") or (data.get("data", {}) or {}).get("content", "")

    if not channel_id or not content:
        return {"ok": True}

    logger.info(f"Discord webhook: message from channel {channel_id}: {content[:50]}")
    handle_incoming_message(channel_id, content)

    return {"ok": True}


# ============================================================================
# INTEGRATIONS — external data sources (databases, CRMs, SaaS APIs)
# ============================================================================

@app.post("/integrations")
def create_integration(req: DataSourceCreateRequest):
    try:
        result = integrations_service.create_data_source(
            name=req.name,
            source_type=req.source_type,
            connection_string=req.connection_string,
            api_endpoint=req.api_endpoint,
            api_key=req.api_key,
            api_headers=req.api_headers,
            query_template=req.query_template,
            field_mappings=req.field_mappings,
            user_identifier_field=req.user_identifier_field,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create integration")
        raise HTTPException(status_code=500, detail=f"Failed to create integration: {exc}") from exc


@app.get("/integrations")
def list_integrations():
    return {"data_sources": integrations_service.list_data_sources()}


@app.post("/integrations/{data_source_id}/test")
def test_integration(data_source_id: str):
    result = integrations_service.test_data_source(data_source_id)
    if not result.get("success") and result.get("error") == "Data source not found":
        raise HTTPException(status_code=404, detail="Data source not found")
    return result


@app.post("/integrations/{data_source_id}/sync")
def sync_integration(data_source_id: str):
    result = integrations_service.sync_data_source(data_source_id)
    if not result.get("success") and result.get("error") == "Data source not found":
        raise HTTPException(status_code=404, detail="Data source not found")
    return result


@app.get("/profile")
def get_business_profile():
    return employee_profile.get_profile()


@app.patch("/profile")
def update_business_profile(req: ProfileUpdateRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    updated = employee_profile.update_profile(**updates)
    if "owner_instructions" in updates:
        employee_learning.learn_from_owner_instruction(updates["owner_instructions"])
    return updated


@app.post("/profile/learn")
def trigger_auto_learn():
    employee_learning.auto_learn_from_all()
    return employee_profile.get_profile()


@app.get("/employees")
def list_employee_roles(active_only: bool = False):
    employee_roles.seed_default_roles()
    return {"roles": employee_roles.list_roles(active_only=active_only)}


@app.get("/employees/{role}")
def get_employee_role(role: str):
    r = employee_roles.get_role(role)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Role '{role}' not found.")
    return r


@app.patch("/employees/{role}")
def update_employee_role(role: str, req: RoleUpdateRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    return employee_roles.upsert_role(role, **updates)


@app.get("/employees/{role}/context")
def get_employee_context(role: str, query: str | None = None, top_k: int = 8):
    return {
        "role": role,
        "personality": employee_skills.get_role_personality(role),
        "context": employee_skills.get_role_skills(role=role, query=query, top_k=top_k),
        "capability_summary": employee_skills.get_capability_summary(),
    }


@app.get("/n8n-workflows")
def list_n8n_workflows(channel: str | None = None, active_only: bool = False):
    return {"workflows": workflows.list_workflows(channel=channel, active_only=active_only)}


@app.post("/n8n-workflows")
def create_n8n_workflow(req: WorkflowCreateRequest):
    return workflows.create_workflow(
        name=req.name, webhook_url=req.webhook_url, description=req.description,
        channels=req.channels, is_active=req.is_active,
    )


@app.get("/n8n-workflows/{workflow_id}")
def get_n8n_workflow(workflow_id: str):
    wf = workflows.get_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


@app.patch("/n8n-workflows/{workflow_id}")
def update_n8n_workflow(workflow_id: str, req: WorkflowUpdateRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    wf = workflows.update_workflow(workflow_id, **updates)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


@app.delete("/n8n-workflows/{workflow_id}")
def delete_n8n_workflow(workflow_id: str):
    deleted = workflows.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return {"deleted": True}


MAX_CSV_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB — stored as a Postgres TEXT column, keep it sane


@app.post("/integrations/csv")
async def create_csv_integration(
    name: str = Form(...),
    user_identifier_field: str = Form("user_id"),
    file: UploadFile = File(...),
):
    """
    Create a CSV data source from an uploaded file. Separate from the
    JSON-only POST /integrations route since this takes actual file
    content, not connection parameters.
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")
    try:
        raw_bytes = await file.read()
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded CSV is empty.")
        if len(raw_bytes) > MAX_CSV_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"CSV too large ({len(raw_bytes) / 1024 / 1024:.1f} MB). Max size is {MAX_CSV_SIZE_BYTES / 1024 / 1024:.0f} MB.",
            )
        csv_text = raw_bytes.decode("utf-8-sig")
        result = integrations_service.create_csv_data_source(
            name=name, csv_content=csv_text, csv_filename=file.filename,
            user_identifier_field=user_identifier_field,
        )
        return result
    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.")
    except Exception as exc:
        logger.exception("CSV data source creation failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Failed to create CSV data source: {exc}") from exc
    finally:
        await file.close()
