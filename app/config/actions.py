import os
import re

import httpx
from nemoguardrails.actions import action
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()

# Singapore-relevant PII patterns to add to Presidio (NRIC/FIN)
_NRIC = re.compile(r"\b[STFG]\d{7}[A-Z]\b")

_JAILBREAK_PATTERNS = [
    r"ignore (all|previous|the) (instructions|rules)",
    r"disregard .* (instructions|rules)",
    r"you are now",
    r"developer mode",
    r"do anything now",
    r"\bDAN\b",
    r"pretend you have no (rules|restrictions)",
    r"reveal your (system )?prompt",
]


@action(name="mask_pii")
async def mask_pii(text: str = "") -> str:
    if not text:
        return text
    results = _analyzer.analyze(text=text, language="en")
    masked = _anonymizer.anonymize(text=text, analyzer_results=results).text
    masked = _NRIC.sub("<NRIC>", masked)
    return masked


@action(name="check_jailbreak")
async def check_jailbreak(text: str = "") -> bool:
    low = (text or "").lower()
    return any(re.search(p, low) for p in _JAILBREAK_PATTERNS)


@action(name="call_eligibility_agent", is_system_action=False)
async def call_eligibility_agent(query: str = "") -> str:
    url = os.getenv("ELIGIBILITY_AGENT_URL", "")
    if not url:
        return "The eligibility agent is not configured."
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, json={"query": query})
            r.raise_for_status()
            return r.json().get("result", "No result.")
    except Exception as e:  # noqa: BLE001
        return f"Eligibility agent error: {e}"
