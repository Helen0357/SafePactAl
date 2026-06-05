"""
Prompt for the ContractAnalysisAgent.

Instructs Gemini to analyze a contract and return a validated JSON risk report.
The schema hint is embedded so Gemini knows the exact output shape expected.
"""

SYSTEM_PROMPT = """\
You are ProtectMe AI, a contract-risk analysis assistant. Your job is to carefully
read the contract provided by the user and identify ALL potentially problematic,
unclear, or one-sided clauses.

STRICT RULES:
1. Return ONLY a single valid JSON object — no prose, no markdown, no code fences.
2. Identify EVERY risk — do not limit to top 3 or top 5. Be exhaustive.
3. Sort risks by severity inside the JSON: High first, then Medium, then Low.
4. Use plain, everyday English in all text fields — your readers are non-lawyers.
5. For clause_text, quote the exact sentence(s) from the contract, verbatim.
6. Assign stable sequential IDs: risk_001, risk_002, risk_003, …
7. If no risks exist, return an empty risks array (never omit the field).
8. confidence is your estimate (0.0–1.0) of how thoroughly you analyzed the contract.

You are NOT a lawyer. Do NOT use legal jargon. Do NOT provide legal opinions.
Frame everything as "you may want to ask" or "this could mean", never as legal advice.
"""

# Schema hint embedded in the user prompt to anchor Gemini's output format
SCHEMA_HINT = """\
{
  "contract_type": "string — e.g. Rental Agreement, Employment Contract, Service Agreement",
  "overall_risk": "High | Medium | Low | Minimal",
  "final_recommendation": "Do Not Sign Yet | Review Before Signing | Sign with Caution | Generally Safe",
  "summary": "string — 2-3 sentence plain-English summary of the main risks found",
  "confidence": 0.85,
  "risks": [
    {
      "id": "risk_001",
      "title": "string — short descriptive title of the risk",
      "severity": "High | Medium | Low",
      "category": "string — e.g. Cancellation, Payment, Privacy, Liability, Entry Rights, Dispute Resolution",
      "clause_text": "string — exact verbatim quote of the relevant clause from the contract",
      "simple_explanation": "string — what this clause means in plain English",
      "why_it_matters": "string — how this clause could specifically harm the user",
      "question_to_ask": "string — one specific question to ask the other party before signing",
      "suggested_action": "Clarify | Negotiate | Reject | Review carefully | Accept"
    }
  ],
  "missing_information": [
    "string — important topic not addressed anywhere in the contract"
  ],
  "recommended_questions": [
    "string — top priority question to ask before signing"
  ]
}"""

ANALYSIS_PROMPT_TEMPLATE = """\
Analyze the following contract and return a JSON risk report using EXACTLY this schema:

{schema}
{language_instruction}
CONTRACT TEXT:
---
{contract_text}
---

Return ONLY the JSON object. No other text before or after it."""

# When the UI language is Arabic, the user-facing TEXT fields must be Arabic, but
# the structural/enum fields stay English so internal logic + validation work.
_ARABIC_INSTRUCTION = """
LANGUAGE INSTRUCTION (IMPORTANT):
Write ALL user-facing text fields in clear Modern Standard Arabic (العربية):
contract_type, summary, final_recommendation, and for EACH risk: title, category,
simple_explanation, why_it_matters, question_to_ask, suggested_action.
Keep the JSON keys themselves in English.
Keep clause_text in the ORIGINAL contract language (verbatim quote — do not translate it).
The fields "overall_risk" and "severity" MUST remain EXACTLY one of the English
values (High | Medium | Low | Minimal) — do NOT translate those two fields.
"""


def build_analysis_prompt(contract_text: str, language: str = "en") -> str:
    """Assemble the final user prompt with schema and contract text.
    language='ar' makes the user-facing fields Arabic (enums stay English)."""
    lang_instruction = _ARABIC_INSTRUCTION if str(language).lower().startswith("ar") else ""
    return ANALYSIS_PROMPT_TEMPLATE.format(
        schema=SCHEMA_HINT,
        language_instruction=lang_instruction,
        contract_text=contract_text,
    )


# Retry prompt used when Gemini's first response cannot be parsed as JSON
JSON_REPAIR_PROMPT_TEMPLATE = """\
The text below was supposed to be a JSON object but it is not valid JSON.
Please fix it so it is valid JSON and return ONLY the corrected JSON object.
Do not add any explanation or surrounding text.

TEXT TO FIX:
{bad_response}"""


def build_repair_prompt(bad_response: str) -> str:
    return JSON_REPAIR_PROMPT_TEMPLATE.format(bad_response=bad_response[:4000])
