import os
import re

import httpx
from jinja2 import Template
from nemoguardrails import RailsConfig

from config.actions import call_eligibility_agent, check_jailbreak, mask_pii
from rag import format_context, retrieve

CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "/app/config")
OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
COUPLES_AND_FAMILIES_LABELS = [
    "Fiancé and fiancée",
    "Married couples and/ or parent(s) with child(ren)",
    "Multi-generation families",
    "Orphaned siblings",
    "Families with non-residents",
]
SINGLES_LABELS = [
    "Singles",
    "Two or more singles",
]

_config = RailsConfig.from_path(CONFIG_PATH)
_prompts = {prompt.task: prompt.content for prompt in _config.prompts}

AGENT_KEYWORDS = {
    "eligibility",
    "eligible",
    "grant",
    "grants",
    "hfe",
    "income ceiling",
    "loan",
    "subsidy",
}
SYSTEM_PROMPT = """You are HDB Assistant, a production-style Singapore HDB information bot.
Answer only from the supplied official HDB context and any eligibility agent output.
If the context does not fully support the answer, say that you do not have enough verified official HDB information.
Keep the answer concise, factual, and easy to understand.
If the question asks who is eligible, list the explicit household categories stated in the HDB context.
Do not treat priority schemes as the main answer unless the user specifically asks about priority schemes.
Do not invent grant amounts, income ceilings, or eligibility rules."""
UNVERIFIED_MESSAGE = (
    "I could not verify a grounded answer from the retrieved official HDB sources. "
    "Please refer to the official sources listed below."
)
NO_CONTEXT_MESSAGE = (
    "I do not have enough retrieved official HDB information to answer that safely. "
    "Please check the official HDB sources below."
)
REFUSAL_MESSAGE = (
    "I can only help with safe, Singapore HDB-related questions. "
    "Please ask about HDB flats, eligibility, grants, loans, rentals, or HDB services."
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def _join_labels(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


async def _ollama_chat(messages: list[dict], temperature: float = 0.1) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{OLLAMA}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
    return data.get("message", {}).get("content", "").strip()


def _render_prompt(task: str, **kwargs) -> str:
    template = _prompts.get(task)
    if not template:
        raise KeyError(f"Missing NeMo prompt template for task '{task}'")
    return Template(template).render(**kwargs)


async def _ask_yes_no(task: str, **kwargs) -> bool:
    prompt = _render_prompt(task, **kwargs)
    answer = await _ollama_chat(
        [
            {"role": "system", "content": "Answer with only one word: yes or no."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    normalized = answer.strip().lower()
    return normalized.startswith("yes")


async def _generate_grounded_answer(question: str, context_text: str) -> str:
    user_prompt = (
        "Use only the official HDB context below.\n\n"
        f"{context_text}\n\n"
        f"Question: {question}\n\n"
        "Answer the question directly. If the context is insufficient, say so clearly.\n"
        "Use the same level of specificity as the evidence. If the context says 'buy a flat', "
        "do not upgrade that into a more specific BTO claim unless the context explicitly says so.\n"
        "When the context lists household categories, list those categories explicitly."
    )
    return await _ollama_chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )


def _rule_based_answer(question: str, chunks: list[dict]) -> str | None:
    low_question = question.lower()
    if not any(term in low_question for term in ["eligible", "eligibility", "who can buy"]):
        return None

    for chunk in chunks:
        source = chunk.get("source", "").lower()
        text = chunk.get("text", "")
        if "couples-and-families" in source:
            labels = [label for label in COUPLES_AND_FAMILIES_LABELS if label.lower() in text.lower()]
            if labels:
                return f"HDB lists these Couples and Families household types: {_join_labels(labels)}."
        if "/singles" in source:
            labels = [label for label in SINGLES_LABELS if label.lower() in text.lower()]
            if labels:
                return f"HDB lists these Singles household types: {_join_labels(labels)}."

    return None


def _lexically_grounded(answer: str, context_text: str) -> bool:
    normalized_context = _normalize_text(context_text)
    context_tokens = set(normalized_context.split())
    segments = [
        segment.strip()
        for segment in re.split(r"[\n.;]+", answer)
        if len(segment.strip().split()) >= 2
    ]
    if not segments:
        return False

    for segment in segments:
        normalized_segment = _normalize_text(segment)
        if not normalized_segment:
            continue
        if normalized_segment in normalized_context:
            continue
        segment_tokens = set(normalized_segment.split())
        if not segment_tokens:
            continue
        overlap = len(segment_tokens & context_tokens) / len(segment_tokens)
        if overlap < 0.8:
            return False

    return True


async def guarded_answer(question: str) -> dict:
    """Run retrieval, optional agent augmentation, then NeMo-configured guardrail checks."""
    if await check_jailbreak(question):
        return {"answer": REFUSAL_MESSAGE, "blocked_by": "guardrail", "sources": [], "agent_used": False}

    if await _ask_yes_no("self_check_input", user_input=question):
        return {"answer": REFUSAL_MESSAGE, "blocked_by": "guardrail", "sources": [], "agent_used": False}

    chunks = retrieve(question)
    sources = list(dict.fromkeys(c["source"] for c in chunks if c.get("source")))
    context_sections = []
    if chunks:
        context_sections.append(format_context(chunks))

    lower_question = question.lower()
    used_agent = any(term in lower_question for term in AGENT_KEYWORDS)
    if used_agent:
        agent_result = await call_eligibility_agent(question)
        if agent_result and "not configured" not in agent_result.lower():
            context_sections.append(f"[Eligibility agent]\n{agent_result}")
        else:
            used_agent = False

    context_text = "\n\n".join(section for section in context_sections if section).strip()
    if not context_text:
        return {
            "answer": NO_CONTEXT_MESSAGE,
            "blocked_by": "no_context",
            "sources": sources,
            "agent_used": used_agent,
        }

    answer = _rule_based_answer(question, chunks)
    if answer is None:
        masked_question = await mask_pii(question)
        answer = await _generate_grounded_answer(masked_question, context_text)
    answer = (await mask_pii(answer)).strip()

    if not answer:
        return {
            "answer": UNVERIFIED_MESSAGE,
            "blocked_by": "generation_error",
            "sources": sources,
            "agent_used": used_agent,
        }

    if await _ask_yes_no("self_check_output", bot_response=answer):
        return {
            "answer": REFUSAL_MESSAGE,
            "blocked_by": "guardrail",
            "sources": sources,
            "agent_used": used_agent,
        }

    grounded = await _ask_yes_no("self_check_facts", evidence=context_text, response=answer)
    if not grounded and not _lexically_grounded(answer, context_text):
        return {
            "answer": UNVERIFIED_MESSAGE,
            "blocked_by": "fact_check",
            "sources": sources,
            "agent_used": used_agent,
        }

    return {
        "answer": answer,
        "blocked_by": None,
        "sources": sources,
        "agent_used": used_agent,
    }
