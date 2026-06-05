"""
Thin wrapper around the google-genai SDK (google-genai 2.x).

Uses the native async API (client.aio.models.generate_content) so FastAPI's
event loop is never blocked and no thread-pool DNS issues occur on Windows.

Two configured model roles:
  analysis_model      — Pro-level, JSON output, long context (contract analysis).
  conversation_model  — Flash-level, streaming, low latency (voice + intent).
"""
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    Wraps google.genai.Client with native async support.
    Initialized lazily on first call.
    """

    def __init__(
        self,
        api_key: str,
        analysis_model: str,
        conversation_model: str,
        live_model: str = "",
        voice_fallback_model: str = "",
    ):
        self._api_key = api_key
        self.analysis_model = analysis_model
        self.conversation_model = conversation_model
        self.live_model = live_model
        # Fastest model for short voice fallback answers; empty → conversation_model.
        self.voice_fallback_model = voice_fallback_model or conversation_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
            logger.info(
                "GeminiClient ready — analysis: %s | conversation: %s | voice_fallback: %s",
                self.analysis_model,
                self.conversation_model,
                self.voice_fallback_model,
            )
        return self._client

    @staticmethod
    def _thinking_config(model_name: str):
        """Low-latency thinking config, per model family.
        Gemini 3.x uses thinking_level='minimal' (Google's Gemini-3 setting);
        Gemini 2.x uses thinking_budget=0. The two are never combined."""
        from google.genai import types

        name = model_name or ""
        try:
            if name.startswith("gemini-3"):
                return types.ThinkingConfig(thinking_level="minimal")
            return types.ThinkingConfig(thinking_budget=0)
        except Exception:  # older SDK / unsupported field
            try:
                return types.ThinkingConfig(thinking_budget=0)
            except Exception:
                return None

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.1,
    ) -> str:
        """
        Single-shot async text generation using the native google-genai async API.
        No thread pool — runs natively in the event loop.
        """
        client = self._get_client()
        model_name = model or self.analysis_model

        from google.genai import types

        config_kwargs: dict = {"temperature": temperature}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if system:
            config_kwargs["system_instruction"] = system
        # Low-latency thinking config (model-aware) so responses are fast.
        tc = self._thinking_config(model_name)
        if tc is not None:
            config_kwargs["thinking_config"] = tc

        config = types.GenerateContentConfig(**config_kwargs)

        logger.debug("Gemini generate -> model=%s json_mode=%s", model_name, json_mode)

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )

        text = response.text or ""
        logger.debug("Gemini generate <- %d chars", len(text))
        return text

    async def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """
        Native async streaming generation. Yields text chunks as they arrive.
        Phase 4: used by ConversationAgent -> SentenceBuffer -> WebSocket.
        """
        client = self._get_client()
        model_name = model or self.conversation_model

        from google.genai import types

        config_kwargs: dict = {"temperature": temperature}
        if system:
            config_kwargs["system_instruction"] = system
        # Voice answers must be snappy: minimal thinking (Gemini 3) / budget 0 (2.x).
        tc = self._thinking_config(model_name)
        if tc is not None:
            config_kwargs["thinking_config"] = tc
        config = types.GenerateContentConfig(**config_kwargs)

        async for chunk in await client.aio.models.generate_content_stream(
            model=model_name,
            contents=prompt,
            config=config,
        ):
            text = getattr(chunk, "text", None) or ""
            if text:
                yield text
