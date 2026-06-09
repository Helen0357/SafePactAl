from enum import Enum
from typing import List
from pydantic import BaseModel, Field, model_validator


class RiskSeverity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class OverallRisk(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    MINIMAL = "Minimal"


class RiskItem(BaseModel):
    """
    One detected risk. All fields have defaults so a single missing field in the
    LLM's JSON output never fails the whole analysis (the model occasionally omits
    one). Structural fields (id, title) are backfilled by RiskReport's validator,
    and blank-but-present fields are filled with safe fallbacks (see below).
    """
    id: str = Field("", description="Stable identifier, e.g. 'risk_001'")
    title: str = Field("Untitled Risk", description="Short risk title")
    severity: RiskSeverity = RiskSeverity.MEDIUM
    category: str = Field("General", description="e.g. 'Cancellation', 'Payment', 'Privacy'")
    clause_text: str = Field("", description="Original extracted clause text or short excerpt")
    simple_explanation: str = Field("", description="Plain-language explanation for non-experts")
    why_it_matters: str = Field("", description="How this risk may harm the user")
    question_to_ask: str = Field("", description="Question to ask the other party before signing")
    suggested_action: str = Field("Review carefully", description="Clarify / Negotiate / Reject / Review carefully / Accept")



_CATEGORY_WHY: list[tuple[tuple[str, ...], str]] = [
    (("maintenance", "repair", "upkeep"),
     "This matters because you may face recurring maintenance costs or unclear responsibility for repairs."),
    (("deposit", "security deposit", "refund"),
     "This matters because you may lose money or face unclear refund conditions."),
    (("renewal", "auto-renew", "auto renew", "extension", "term length", "duration"),
     "This matters because you could be locked into the agreement longer than expected."),
    (("payment", "fee", "charge", "penalty", "late", "fine", "interest"),
     "This matters because you may face unexpected or extra charges."),
    (("termination", "cancel", "early exit", "break lease", "notice period"),
     "This matters because leaving the agreement early could be costly or difficult."),
    (("liability", "indemnif", "damage", "responsib", "negligence"),
     "This matters because you could be held responsible for costs or damages you did not expect."),
    (("privacy", "data", "confidential", "personal information"),
     "This matters because your personal information may be used or shared in ways you did not intend."),
]

_SEVERITY_WHY: dict[str, str] = {
    "High": "This may create serious financial or legal risk if it is not clarified before signing.",
    "Medium": "This may create extra cost, responsibility, or uncertainty for you.",
    "Low": "This may cause minor inconvenience or unclear expectations later.",
}


def fallback_why_it_matters(title: str, category: str, severity: str) -> str:
    """Generate a non-empty 'why it matters' from category, then severity."""
    hay = f"{category} {title}".lower()
    for keys, msg in _CATEGORY_WHY:
        if any(k in hay for k in keys):
            return msg
    return _SEVERITY_WHY.get(severity, _SEVERITY_WHY["Medium"])


def fill_risk_item_fallbacks(risk: "RiskItem") -> "RiskItem":
    """Fill any blank field on a RiskItem with a safe, non-empty fallback."""
    sev = risk.severity.value if hasattr(risk.severity, "value") else str(risk.severity)
    if not (risk.title or "").strip():
        risk.title = "Unnamed clause"
    if not (risk.category or "").strip():
        risk.category = "General"
    if not (risk.why_it_matters or "").strip():
        risk.why_it_matters = fallback_why_it_matters(risk.title, risk.category, sev)
    if not (risk.simple_explanation or "").strip():
        risk.simple_explanation = (
            f"This clause relates to {risk.category.lower()} in your contract "
            "and may affect your rights or obligations."
        )
    if not (risk.clause_text or "").strip():
        risk.clause_text = (
            "The exact clause wording was not captured during analysis — "
            "see the plain-language explanation below."
        )
    if not (risk.question_to_ask or "").strip():
        risk.question_to_ask = (
            "Can you clarify how this clause applies to me, and confirm the details in writing?"
        )
    if not (risk.suggested_action or "").strip():
        risk.suggested_action = "Review carefully"
    return risk


class RiskReport(BaseModel):
    contract_type: str = Field("Contract", description="e.g. 'Rental Agreement', 'Employment Contract'")
    overall_risk: OverallRisk = OverallRisk.MEDIUM
    final_recommendation: str = Field("Review Before Signing", description="e.g. 'Do Not Sign Yet', 'Review Before Signing'")
    summary: str = Field("", description="Short human-readable summary of the contract risks")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Analysis confidence score 0–1")
    risks: List[RiskItem] = Field(default_factory=list, description="All detected risks, sorted High→Medium→Low")
    missing_information: List[str] = Field(default_factory=list)
    recommended_questions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _backfill_risk_ids(self) -> "RiskReport":
        """Assign sequential ids to any risk the model left without one,
        so clause selection / active-clause lookups always have a stable key."""
        seen: set[str] = set()
        for i, risk in enumerate(self.risks, start=1):
            if not risk.id or risk.id in seen:
                risk.id = f"risk_{i:03d}"
            seen.add(risk.id)
        return self

    @model_validator(mode="after")
    def _normalize_risk_fields(self) -> "RiskReport":
        """Fill any blank risk field with a safe fallback so the dashboard and
        voice agent never surface an empty 'why it matters' (or other) section."""
        for risk in self.risks:
            fill_risk_item_fallbacks(risk)
        return self
