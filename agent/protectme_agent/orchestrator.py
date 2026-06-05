"""
Custom lightweight agent orchestrator using the Gemini API.
Designed to be ADK-compatible for future migration.

Coordinates two agent workflows:
  1. ContractAnalysisAgent (Phase 2) — analyzes a contract, returns risk report dict.
  2. ConversationAgent     (Phase 4) — session-aware follow-up, intent routing, tools.
"""
import logging

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Top-level coordinator injected into backend services.

    Future ADK migration:
      Replace _analysis_agent.analyze() with ADK Agent.run() while keeping
      the same prompt, session, and schema layers untouched.
    """

    def __init__(self, gemini_client=None):
        self._client = gemini_client
        self._analysis_agent = None
        self._conversation_agent = None  # Phase 4

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_analysis_agent(self):
        if self._analysis_agent is None:
            from protectme_agent.contract_analysis_agent import ContractAnalysisAgent
            self._analysis_agent = ContractAnalysisAgent(self._client)
        return self._analysis_agent

    # ── Public API ────────────────────────────────────────────────────────────

    async def analyze_contract(self, text: str, language: str = "en") -> dict:
        """
        Analyze contract text and return a risk report as a plain dict
        (ready to store in the session and serialize to JSON).
        language='ar' makes the user-facing fields Arabic (enums stay English).
        """
        agent = self._get_analysis_agent()
        report = await agent.analyze(text, language=language)
        # mode='json' ensures enum values are strings, datetimes are ISO strings, etc.
        return report.model_dump(mode="json")

    async def handle_conversation_turn(
        self,
        session_id: str,
        transcript: str,
        session_context: dict,
    ) -> dict:
        """
        Phase 4: route user intent, dispatch tools, stream response sentences.
        """
        raise NotImplementedError("Phase 4 implementation.")
