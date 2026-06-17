import json

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# PLACEHOLDER figures. Replace with current official HDB values before demo.
RULES = {
    "bto_income_ceiling_family": 14000,
    "bto_income_ceiling_singles": 7000,
    "ehg_max_grant": 120000,
    "citizen_required": True,
}


def assess(query: str) -> str:
    q = query.lower()
    parts = []
    if "income" in q or "ceiling" in q or "eligib" in q:
        parts.append(
            f"Indicative BTO income ceiling: family ${RULES['bto_income_ceiling_family']}, "
            f"singles ${RULES['bto_income_ceiling_singles']} (verify on hdb.gov.sg)."
        )
    if "grant" in q or "ehg" in q:
        parts.append(
            f"Enhanced CPF Housing Grant can be up to ${RULES['ehg_max_grant']} "
            f"depending on household income (verify on hdb.gov.sg)."
        )
    if not parts:
        parts.append("Ask about BTO income ceilings or housing grants.")
    return " ".join(parts)


@app.route(route="eligibility", methods=["POST"])
def eligibility(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        body = {}
    result = assess(body.get("query", ""))
    return func.HttpResponse(
        json.dumps({"result": result}), mimetype="application/json"
    )
