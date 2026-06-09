"""
Tool: generate_message

Generates a professional message (email or WhatsApp) targeting one or more
identified contract risks. Dispatched by MessageService when a draft is requested.
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class GenerateMessageTool:
    """
    Input:  clause_texts + risk_titles + message_type + tone + format + gemini_client
    Output: formatted message draft string
    """

    async def execute(
        self,
        clause_texts: List[str],
        risk_titles: List[str],
        message_type: str,
        tone: str,
        format: str,
        gemini_client=None,
        extra_instruction: Optional[str] = None,
        language: str = "en",
    ) -> str:
        if not clause_texts:
            raise ValueError("No clause texts provided.")
        if gemini_client is None:
            raise ValueError("gemini_client is required.")

        from protectme_agent.prompts.message_generation_prompt import (
            SYSTEM_PROMPT,
            build_message_prompt,
        )

        prompt = build_message_prompt(
            risk_summaries=risk_titles,
            clause_texts=clause_texts,
            message_type=message_type,
            tone=tone,
            format=format,
            extra_instruction=extra_instruction,
            language=language,
        )

        logger.debug(
            "GenerateMessageTool: type=%s tone=%s format=%s clauses=%d",
            message_type,
            tone,
            format,
            len(clause_texts),
        )

        draft = await gemini_client.generate(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=gemini_client.conversation_model,
            temperature=0.3,
        )
        return draft.strip()
