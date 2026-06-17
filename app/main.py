import logging
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel

from auth import create_token, current_user
from db import ChatLog, SessionLocal, User, init_db, verify_password
from telemetry import chat_latency, rail_block_counter, setup_telemetry, tracer

setup_telemetry()
log = logging.getLogger("hdb-api")
HDB_TOPICS = [
    "BTO flats",
    "resale flats",
    "eligibility and HFE",
    "CPF housing grants",
    "HDB housing loans",
    "public rental scheme",
    "renting from the open market",
    "renting out a flat",
    "renovation and home ownership services",
]

app = FastAPI(title="HDB Guardrailed Assistant", version="1.0.0")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


class ChatIn(BaseModel):
    message: str
    image_b64: str | None = None  # documented multimodal hook (Section 8.6)


class ChatOut(BaseModel):
    answer: str
    sources: list[str]
    blocked_by: str | None = None
    agent_used: bool = False


class ChatHistoryItem(BaseModel):
    question: str
    answer: str
    blocked_by: str | None = None
    created_at: str | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str
    username: str


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # import here so telemetry + db are ready before NeMo loads the model
    global guarded_answer
    from guardrails_runner import guarded_answer  # noqa: F401


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/topics")
def topics() -> dict:
    return {"topics": HDB_TOPICS}


@app.get("/me")
def me(user: str = Depends(current_user)) -> dict:
    return {"username": user}


@app.post("/auth/token", response_model=LoginOut)
def token(form: OAuth2PasswordRequestForm = Depends()) -> LoginOut:
    with SessionLocal() as s:
        user = s.query(User).filter_by(username=form.username).first()
        if not user or not verify_password(form.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Bad credentials")
    return LoginOut(
        access_token=create_token(form.username),
        token_type="bearer",
        username=form.username,
    )


@app.get("/chat/history", response_model=list[ChatHistoryItem])
def chat_history(user: str = Depends(current_user), limit: int = 15) -> list[ChatHistoryItem]:
    safe_limit = max(1, min(limit, 50))
    with SessionLocal() as s:
        rows = (
            s.query(ChatLog)
            .filter_by(username=user)
            .order_by(ChatLog.created_at.desc())
            .limit(safe_limit)
            .all()
        )
    return [
        ChatHistoryItem(
            question=row.question,
            answer=row.answer,
            blocked_by=row.blocked_by,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, user: str = Depends(current_user)) -> ChatOut:
    start = time.time()
    with tracer.start_as_current_span("chat_request") as span:
        span.set_attribute("user", user)
        from guardrails_runner import guarded_answer

        result = await guarded_answer(body.message)

        if result["blocked_by"]:
            rail_block_counter.add(1, {"rail": result["blocked_by"]})
            span.set_attribute("blocked_by", result["blocked_by"])

        with SessionLocal() as s:
            s.add(
                ChatLog(
                    username=user,
                    question=body.message,
                    answer=result["answer"],
                    blocked_by=result["blocked_by"],
                )
            )
            s.commit()

        chat_latency.record((time.time() - start) * 1000.0, {"user": user})
        log.info("chat handled user=%s blocked=%s", user, result["blocked_by"])
        return ChatOut(**result)
