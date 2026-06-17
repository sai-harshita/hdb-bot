import logging
import os
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


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # import here so telemetry + db are ready before NeMo loads the model
    global guarded_answer
    from guardrails_runner import guarded_answer  # noqa: F401


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/auth/token")
def token(form: OAuth2PasswordRequestForm = Depends()) -> dict:
    with SessionLocal() as s:
        user = s.query(User).filter_by(username=form.username).first()
        if not user or not verify_password(form.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Bad credentials")
    return {"access_token": create_token(form.username), "token_type": "bearer"}


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
