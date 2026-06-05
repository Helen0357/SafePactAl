"""
ContractAnalysisAgent — Phase 2 core implementation.

Analyzes a contract text using Gemini Pro and returns a validated RiskReport.

Flow:
  1. Build analysis prompt (system + schema + contract text).
  2. Call GeminiClient.generate() with JSON mode enabled.
  3. Extract JSON from response (handles markdown fences, prose wrapping).
  4. If extraction fails → retry once with a JSON repair prompt.
  5. Validate the parsed dict with the RiskReport Pydantic schema.
  6. Sort risks High → Medium → Low.
  7. Return the validated RiskReport.

Logging follows the [Agent] prefix convention used by the debug terminal.
"""
import json
import logging
from typing import TYPE_CHECKING

from protectme_agent.prompts.contract_analysis_prompt import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    build_repair_prompt,
)
from protectme_agent.schemas.risk_report_schema import RiskReport, RiskSeverity

if TYPE_CHECKING:
    from protectme_agent.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {RiskSeverity.HIGH: 0, RiskSeverity.MEDIUM: 1, RiskSeverity.LOW: 2}


def _extract_json(text: str) -> dict | None:
    """
    Extract a JSON object from raw Gemini output.
    Handles: direct JSON, ```json ... ```, ``` ... ```, or a {...} substring.
    """
    import re

    # 1. Direct parse
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    for pattern in (r"```(?:json)?\s*([\s\S]+?)\s*```", r"`([\s\S]+?)`"):
        match = re.search(pattern, stripped, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue

    # 3. Find the outermost { … } block
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


class ContractAnalysisAgent:
    """
    Analyzes a contract and returns a structured, validated RiskReport.
    Injected with a GeminiClient by the Orchestrator.
    """

    def __init__(self, gemini_client: "GeminiClient"):
        self.client = gemini_client

    async def analyze(self, contract_text: str, language: str = "en") -> RiskReport:
        """
        Run the full analysis pipeline and return a validated RiskReport.
        language='ar' makes the user-facing fields Arabic (enums stay English).

        Raises:
            ValueError: if JSON cannot be parsed even after repair.
            pydantic.ValidationError: if the parsed JSON doesn't match the schema.
        """
        logger.info("[Agent] Contract analysis started — %d chars (lang=%s)",
                    len(contract_text), language)

        prompt = build_analysis_prompt(contract_text, language=language)

        # ── Attempt 1: standard analysis ─────────────────────────────────────
        raw = await self.client.generate(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=self.client.analysis_model,
            json_mode=True,
            temperature=0.1,
        )
        logger.debug("[Agent] Gemini raw response length: %d chars", len(raw))

        data = _extract_json(raw)

        # ── Attempt 2: JSON repair ────────────────────────────────────────────
        if data is None:
            logger.warning(
                "[Agent] Could not parse JSON from first attempt — retrying with repair prompt."
            )
            repair_prompt = build_repair_prompt(raw)
            repaired_raw = await self.client.generate(
                prompt=repair_prompt,
                model=self.client.conversation_model,  # faster model for repair
                json_mode=True,
                temperature=0.0,
            )
            data = _extract_json(repaired_raw)

        if data is None:
            raise ValueError(
                "Contract analysis failed: Gemini did not return parsable JSON "
                "on two attempts. Please try again or simplify the contract text."
            )

        logger.info(
            "[Agent] JSON extracted — %d risks detected before validation.",
            len(data.get("risks", [])),
        )

        # ── Pydantic validation ───────────────────────────────────────────────
        report = RiskReport(**data)

        # ── Sort risks High → Medium → Low ────────────────────────────────────
        report.risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 9))

        high = sum(1 for r in report.risks if r.severity == RiskSeverity.HIGH)
        med  = sum(1 for r in report.risks if r.severity == RiskSeverity.MEDIUM)
        low  = sum(1 for r in report.risks if r.severity == RiskSeverity.LOW)
        logger.info(
            "[Agent] Analysis complete — overall: %s | risks: %d total (%dH %dM %dL)",
            report.overall_risk.value,
            len(report.risks),
            high, med, low,
        )

        return report
