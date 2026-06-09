"""
Risk report schema for the agent package.
Mirrors backend/app/schemas/risk_schema.py exactly.
If the schema changes, update both files together.
"""
from enum import Enum
from typing import List, Optional
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
    One detected risk. Every field has a default so a single missing key in the
    LLM's JSON output never fails the whole analysis (Gemini occasionally omits
    one, e.g. why_it_matters). Missing/duplicate ids are backfilled by RiskReport.
    Blank-but-present fields (Gemini returning "") are filled with safe fallbacks
    by RiskReport's normalization validator.
    """
    id: str = ""
    title: str = "Untitled Risk"
    severity: RiskSeverity = RiskSeverity.MEDIUM
    category: str = "General"
    clause_text: str = ""
    simple_explanation: str = ""
    why_it_matters: str = ""
    question_to_ask: str = ""
    suggested_action: str = "Review carefully"


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
    """Fill any blank field on a RiskItem with a safe, non-empty fallback so no
    risk card / voice answer ever has an empty section."""
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
    contract_type: str = "Contract"
    overall_risk: OverallRisk = OverallRisk.MEDIUM
    final_recommendation: str = "Review Before Signing"
    summary: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    risks: List[RiskItem] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    recommended_questions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _backfill_risk_ids(self) -> "RiskReport":
        """Assign sequential ids to any risk the model left without one (or with a
        duplicate), so clause selection / active-clause lookups have a stable key."""
        seen: set[str] = set()
        for i, risk in enumerate(self.risks, start=1):
            if not risk.id or risk.id in seen:
                risk.id = f"risk_{i:03d}"
            seen.add(risk.id)
        return self

    @model_validator(mode="after")
    def _normalize_risk_fields(self) -> "RiskReport":
        """Fill any blank risk field with a safe fallback before storage, so the
        dashboard and voice agent never surface an empty 'why it matters' (or any
        other) section. See fill_risk_item_fallbacks."""
        for risk in self.risks:
            fill_risk_item_fallbacks(risk)
        return self

    def get_by_severity(self, severity: RiskSeverity) -> List[RiskItem]:
        return [r for r in self.risks if r.severity == severity]

    def get_by_id(self, risk_id: str) -> Optional[RiskItem]:
        return next((r for r in self.risks if r.id == risk_id), None)

    def sorted_risks(self) -> List[RiskItem]:
        order = {RiskSeverity.HIGH: 0, RiskSeverity.MEDIUM: 1, RiskSeverity.LOW: 2}
        return sorted(self.risks, key=lambda r: order.get(r.severity, 9))
