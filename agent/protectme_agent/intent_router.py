"""
IntentRouter — classifies a user's free-text input into one of 8 intent classes
using a fast Gemini call.

Used by ConversationAgent (Phase 4) and unit-testable independently in Phase 3.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_FALLBACK_CLARIFICATION = (
    "I'm not sure what you'd like to do. "
    "Should I write a message, explain a clause, or suggest questions to ask?"
)


class IntentRouter:
    """
    Routes a free-text user message to one of 8 intent classes.
    If confidence < 0.6, intent is forced to 'unclear' and a clarification
    question is attached.
    """

    def __init__(self, gemini_client):
        self._client = gemini_client

    async def route(
        self,
        user_input: str,
        active_clause_id: Optional[str] = None,
    ):
        """
        Classify user_input and return an IntentResult.
        Never raises — on any parse failure returns intent=unclear.
        """
        from protectme_agent.prompts.intent_router_prompt import build_intent_prompt
        from protectme_agent.schemas.intent_schema import Intent, IntentResult

        prompt = build_intent_prompt(user_input, active_clause_id)

        try:
            raw = await self._client.generate(
                prompt=prompt,
                model=self._client.conversation_model,
                json_mode=True,
                temperature=0.0,
            )
            data = json.loads(raw)
            result = IntentResult(**data)
        except Exception as exc:
            logger.warning("IntentRouter parse error: %s — defaulting to unclear", exc)
            return IntentResult(
                intent=Intent.UNCLEAR,
                confidence=0.0,
                clarification_question=_FALLBACK_CLARIFICATION,
            )

        if result.confidence < 0.6 and result.intent != Intent.UNCLEAR:
            result = result.model_copy(update={"intent": Intent.UNCLEAR})

        if result.needs_clarification and not result.clarification_question:
            result = result.model_copy(
                update={"clarification_question": _FALLBACK_CLARIFICATION}
            )

        logger.debug(
            "IntentRouter: input=%r intent=%s confidence=%.2f",
            user_input[:60],
            result.intent,
            result.confidence,
        )
        return result
