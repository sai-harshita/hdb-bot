import os

from nemoguardrails import LLMRails, RailsConfig

from rag import format_context, retrieve

CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "/app/config")

_config = RailsConfig.from_path(CONFIG_PATH)
rails = LLMRails(_config)

# Register the custom actions defined in config/actions.py.
# NeMo auto-discovers actions.py in the config folder, but we register the
# eligibility agent explicitly so the execution rail can call it.
from config.actions import call_eligibility_agent  # noqa: E402

rails.register_action(call_eligibility_agent, name="call_eligibility_agent")


async def guarded_answer(question: str) -> dict:
    """Run retrieval, then the full guardrails pipeline grounded on chunks."""
    chunks = retrieve(question)
    context_text = format_context(chunks)

    messages = [
        {"role": "context", "content": {"relevant_chunks": context_text}},
        {"role": "user", "content": question},
    ]
    result = await rails.generate_async(messages=messages)

    answer = result["content"] if isinstance(result, dict) else str(result)

    # Detect if a rail blocked the request (NeMo returns the refusal text)
    blocked = None
    refusals = ["cannot help with that", "can only help with Singapore HDB"]
    if any(r in answer.lower() for r in refusals):
        blocked = "guardrail"

    return {
        "answer": answer,
        "blocked_by": blocked,
        "sources": [c["source"] for c in chunks],
    }
