import os
import re
import unicodedata

import httpx
from jinja2 import Template
from nemoguardrails import RailsConfig

from config.actions import call_eligibility_agent, check_jailbreak, mask_pii
from rag import format_context, retrieve

CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "/app/config")
OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

FAMILY_LABELS = [
    ("Fiance and fiancee", "fiance and fiancee"),
    ("Married couples and/or parent(s) with child(ren)", "married couples and/ or parent(s) with child(ren)"),
    ("Multi-generation families", "multi-generation families"),
    ("Orphaned siblings", "orphaned siblings"),
    ("Families with non-residents", "families with non-residents"),
]
SINGLES_LABELS = [
    ("Singles", "singles"),
    ("Two or more singles", "two or more singles"),
]
PRIORITY_SCHEME_LABELS = [
    ("First-timer families", "first-timer families"),
    ("FT(PMC) category", "ft(pmc) category"),
    ("Family and Parenthood Priority Scheme (FPPS)", "family and parenthood priority scheme"),
    ("Family Care Scheme (FCS) (Proximity)", "family care scheme (fcs) (proximity)"),
    ("Family Care Scheme (FCS) (Joint Balloting)", "family care scheme (fcs) (joint balloting)"),
    ("Third Child Priority Scheme (TCPS)", "third child priority scheme"),
    ("ASSIST", "assistance scheme for second-timers"),
    ("Senior Priority Scheme (SPS)", "senior priority scheme"),
    ("Tenants' Priority Scheme (TPS)", "tenants priority scheme"),
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


def _ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def _normalize_text(text: str) -> str:
    folded = _ascii_fold(text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", folded.lower())).strip()


def _join_labels(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _extract_labels(text: str, label_pairs: list[tuple[str, str]]) -> list[str]:
    normalized_text = _normalize_text(text)
    matches = []
    for display, matcher in label_pairs:
        if _normalize_text(matcher) in normalized_text:
            matches.append(display)
    return matches


def _find_chunk(chunks: list[dict], source_fragment: str) -> dict | None:
    needle = source_fragment.lower()
    for chunk in chunks:
        if needle in chunk.get("source", "").lower():
            return chunk
    return None


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
    return answer.strip().lower().startswith("yes")


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


def _rule_based_answer(question: str, chunks: list[dict]) -> tuple[str | None, str]:
    low_question = question.lower()

    family_chunk = _find_chunk(chunks, "couples-and-families")
    singles_chunk = _find_chunk(chunks, "/singles")
    hfe_chunk = _find_chunk(chunks, "application-for-an-hdb-flat-eligibility-hfe-letter")
    resale_chunk = _find_chunk(chunks, "process-for-buying-a-resale-flat")
    new_flat_chunk = _find_chunk(chunks, "process-for-buying-a-new-flat")
    priority_chunk = _find_chunk(chunks, "priority-schemes")
    renovation_chunk = _find_chunk(chunks, "renovation-guidelines/building-works")

    if family_chunk and any(term in low_question for term in ["family", "families", "eligible", "eligibility", "who can buy"]):
        labels = _extract_labels(family_chunk.get("text", ""), FAMILY_LABELS)
        if labels:
            return f"HDB lists these Couples and Families household types: {_join_labels(labels)}.", "extractive"

    if singles_chunk and any(term in low_question for term in ["single", "singles"]):
        labels = _extract_labels(singles_chunk.get("text", ""), SINGLES_LABELS)
        if labels:
            return f"HDB's Singles page covers: {_join_labels(labels)}.", "extractive"

    if hfe_chunk and "hfe" in low_question:
        return (
            "The HFE letter is the HDB Flat Eligibility letter. HDB's HFE page says to plan and apply early, "
            "review how to apply, check the income guidelines and documents, understand the letter's validity "
            "and possible review, and then follow the next steps with your HFE letter.",
            "extractive",
        )

    if resale_chunk and "resale" in low_question:
        return (
            "HDB's resale flat process covers resale flat planning for buyers, the Option to Purchase (OTP), "
            "the resale flat application for buyers, and resale flat completion for buyers.",
            "extractive",
        )

    if priority_chunk and any(term in low_question for term in ["priority", "scheme", "schemes", "first-timer", "ballot"]):
        labels = _extract_labels(priority_chunk.get("text", ""), PRIORITY_SCHEME_LABELS)
        if labels:
            return f"HDB's priority schemes page covers: {_join_labels(labels)}.", "extractive"

    if new_flat_chunk and any(term in low_question for term in ["new flat", "bto", "sbf", "open booking"]):
        return (
            "HDB's new flat buying process covers the overview, modes of sale, application for a new flat, "
            "booking of flat, signing the Agreement for Lease, and key collection.",
            "extractive",
        )

    if renovation_chunk and any(term in low_question for term in ["renovation", "building works", "contractor", "false ceiling", "household shelter"]):
        return (
            "HDB's renovation guidelines for building works cover floor finishes, walls, wall finishes, "
            "false ceiling and cornices, kitchen works, refuse chute hopper alterations, household shelters, "
            "doors and gates, and sold recess area works.",
            "extractive",
        )

    return None, "generated"


def _lexically_grounded(answer: str, context_text: str) -> bool:
    normalized_context = _normalize_text(context_text)
    context_tokens = set(normalized_context.split())
    segments = [
        segment.strip()
        for segment in re.split(r"[\n.;:]+", answer)
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
        if overlap < 0.72:
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

    answer, answer_mode = _rule_based_answer(question, chunks)
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

    if answer_mode != "extractive":
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
