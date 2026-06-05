"""
ConversationAgent — session-aware conversational agent.

Receives user text, routes intent via IntentRouter, dispatches tools,
and yields WebSocket-ready event dicts back to VoiceService.

Async generator pattern: handle_turn() yields events one by one so
VoiceService can forward them to the WebSocket as they are produced.
"""
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class _FastIntent:
    """Minimal intent stand-in for the fast-path generate_message branch.
    _handle_generate_message falls back to session.active_clause_id when
    target_clause_ids is empty, and to sensible defaults for the rest.
    format / extra_instruction carry the channel + length parsed from the user
    text (e.g. 'write a whatsapp message, make it short')."""

    def __init__(self, target_clause_ids=None, message_type=None, tone=None,
                 format=None, extra_instruction=None):
        self.target_clause_ids = target_clause_ids or []
        self.message_type = message_type
        self.tone = tone
        self.format = format
        self.extra_instruction = extra_instruction


class ConversationAgent:
    """
    Orchestrates a single conversation turn:
      1. Routes intent via IntentRouter
      2. Dispatches to the appropriate tool handler
      3. Yields event dicts (status, sentence, debug, tool_result, draft_ready)
    """

    def __init__(self, gemini_client):
        self._client = gemini_client
        self._router = None

    def _get_router(self):
        if self._router is None:
            from protectme_agent.intent_router import IntentRouter
            self._router = IntentRouter(self._client)
        return self._router

    async def handle_turn(self, user_text: str, session) -> AsyncIterator[dict]:
        """Async generator: yields event dicts for each step of the turn.

        Smart route order (Phase 8F-mod + bugfix):
          1. Modify the latest draft       ("make it shorter", "rewrite it")
          2. Arabic request                 ("explain in Arabic", Arabic script)
          3. Clause / risk number reference ("explain clause 6", "the sixth risk")
          4. Severity-specific query        ("the low risk", "first high risk")
          5. Deeper/easier explanation      ("explain more", "I didn't understand")
          6. Deterministic fast path        (biggest risk, explain, should I sign…)
          7. Situational recommendation     ("should I reject", "can he charge me")
          8. Gemini intent router + tools / short grounded fallback
        """
        from protectme_agent import fast_path as fp

        yield {"type": "status", "state": "thinking", "label": "Understanding your request..."}

        report = session.risk_report

        # 1. Modify the most recent generated draft (memory of last action).
        #    Guard: a clear "write a (new) message" request is a generation, not
        #    an edit — e.g. "write a whatsapp message, make it short".
        if (report and fp.wants_modify(user_text) and not fp.wants_generate(user_text)
                and getattr(session, "generated_messages", None)):
            async for event in self._handle_modify_message(user_text, session):
                yield event
            return

        # 2. Arabic — route Arabic (or "explain in Arabic") questions to the
        #    Arabic-aware handler: same fast-path intents, answered in Arabic.
        if report and fp.detect_language(user_text) == "ar":
            async for event in self._handle_arabic_routed(user_text, session):
                yield event
            return

        # 3. Explicit clause / risk number reference ("explain clause 6").
        #    Runs before the generic explain fast path so a number reference
        #    overrides any stale active clause.
        if report and fp.parse_clause_number(user_text) is not None:
            async for event in self._handle_clause_number(user_text, session):
                yield event
            return

        # 4. Severity-specific query ("the low risk", "first high risk").
        if report and fp.severity_query(user_text) is not None:
            async for event in self._handle_severity_query(user_text, session):
                yield event
            return

        # 5. Deeper / easier explanation of the focused clause (richer, not a repeat).
        if report and fp.wants_detail(user_text) and session.active_clause_id:
            detail = fp.build_detail_explain_answer(report, session.active_clause_id)
            if detail:
                yield {"type": "debug", "log": f"[FastPath] detail_explain using {session.active_clause_id}"}
                for s in detail:
                    if s and s.strip():
                        yield {"type": "sentence", "text": s.strip()}
                yield {"type": "status", "state": "idle", "label": "Ready"}
                return

        # 6. Deterministic fast path from the risk_report (no Gemini).
        if report:
            async for event in self._try_fast_path(user_text, session):
                if event.get("type") == "__fastpath_miss__":
                    break  # not handled — continue below
                yield event
            else:
                return  # generator finished without a miss → fully handled

        # 7. Situational recommendation (careful, contextual, never legal certainty).
        if report and fp.is_recommendation(user_text):
            async for event in self._handle_recommendation(user_text, session):
                yield event
            return

        router = self._get_router()
        intent_result = await router.route(user_text, session.active_clause_id)

        yield {
            "type": "debug",
            "log": (
                f"[IntentRouter] intent={intent_result.intent.value} "
                f"confidence={intent_result.confidence:.2f}"
            ),
        }

        if intent_result.needs_clarification:
            question = intent_result.clarification_question or (
                "I'm not sure what you'd like to do. "
                "Should I write a message, explain a clause, or suggest questions?"
            )
            yield {"type": "sentence", "text": question}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        intent = intent_result.intent.value

        if intent == "generate_message":
            async for event in self._handle_generate_message(intent_result, session):
                yield event
        elif intent == "explain_clause":
            async for event in self._handle_explain_clause(intent_result, session):
                yield event
        elif intent == "generate_questions":
            async for event in self._handle_generate_questions(intent_result, session):
                yield event
        else:
            # ask_question, summarize_risks, ask_recommendation, modify_message
            async for event in self._handle_general(user_text, session):
                yield event

    # ── Fast Smart Path ─────────────────────────────────────────────────────

    async def _try_fast_path(self, user_text: str, session) -> AsyncIterator[dict]:
        """
        Try to answer from the risk_report with no Gemini call.
        Yields a single {"type": "__fastpath_miss__"} sentinel (and nothing else)
        when it can't handle the request, so the caller falls through to routing.
        """
        from protectme_agent import fast_path as fp

        key = fp.match_fast_path(user_text)
        if not key:
            yield {"type": "__fastpath_miss__"}
            return

        report = session.risk_report
        active_id = session.active_clause_id

        # generate_message still uses the tool to write the draft, but we skip
        # the intent-router round-trip and trigger it deterministically — ONLY
        # when a clause is in focus. Without an active clause we can't know which
        # clause the message is about, so fall through to the router (the LLM can
        # resolve clause references from the user's phrasing).
        if key == fp.GENERATE_MESSAGE:
            if not active_id:
                yield {"type": "__fastpath_miss__"}
                return
            # Parse the channel (WhatsApp vs email) and any "make it short" hint
            # from the user text so the draft matches what they actually asked for.
            fmt = fp.detect_message_format(user_text)
            extra = fp.message_extra_instruction(user_text)
            yield {
                "type": "debug",
                "log": f"[FastPath] matched=generate_message format={fmt or 'default'}"
                       + (f" extra='{extra}'" if extra else ""),
            }
            intent = _FastIntent(format=fmt, extra_instruction=extra)
            async for event in self._handle_generate_message(intent, session):
                yield event
            return

        if key == fp.BIGGEST_RISK:
            ans = fp.build_biggest_risk_answer(report)
        elif key == fp.EXPLAIN_CLAUSE:
            ans = fp.build_explain_answer(report, active_id) if active_id else None
        elif key == fp.SHOULD_I_SIGN:
            ans = fp.build_should_sign_answer(report)
        elif key == fp.WHAT_TO_ASK:
            ans = fp.build_questions_answer(report, active_id)
        else:
            ans = None

        if not ans:
            yield {"type": "__fastpath_miss__"}
            return

        if key == fp.EXPLAIN_CLAUSE:
            yield {"type": "debug", "log": f"[Voice] active clause loaded: {active_id}"}
            yield {"type": "debug", "log": f"[FastPath] explain_active_clause using {active_id}"}
        yield {"type": "debug", "log": f"[FastPath] answered={key} (no Gemini call)"}

        # Note: we do NOT emit a "speaking" status here. The frontend flips to
        # "speaking" only when audio playback actually begins (real state).
        sentences = ans if isinstance(ans, list) else [ans]
        for s in sentences:
            if s and s.strip():
                yield {"type": "sentence", "text": s.strip()}
        yield {"type": "status", "state": "idle", "label": "Ready"}

    async def _emit_text_answer(self, answer, debug_log: str) -> AsyncIterator[dict]:
        """Emit a deterministic answer (str or list of sentences) + idle status.
        Frontend owns the 'speaking' state, so we don't emit it here."""
        yield {"type": "debug", "log": debug_log}
        sentences = answer if isinstance(answer, list) else [answer]
        for s in sentences:
            if s and s.strip():
                yield {"type": "sentence", "text": s.strip()}
        yield {"type": "status", "state": "idle", "label": "Ready"}

    async def _handle_clause_number(self, user_text: str, session) -> AsyncIterator[dict]:
        """Explain the risk referenced by number ('explain clause 6' → risk_006)."""
        from protectme_agent import fast_path as fp

        report = session.risk_report
        n = fp.parse_clause_number(user_text)
        risk = fp.resolve_clause_by_number(report, n)
        resolved = risk.get("id") if risk else "not_found"
        ans = fp.build_clause_number_answer(report, user_text)
        async for event in self._emit_text_answer(
            ans, f"[FastPath] clause_number={n} -> {resolved}"
        ):
            yield event

    async def _handle_severity_query(self, user_text: str, session) -> AsyncIterator[dict]:
        """Answer a severity-specific query ('the low risk', 'first high risk')."""
        from protectme_agent import fast_path as fp

        report = session.risk_report
        sq = fp.severity_query(user_text)
        ans = fp.build_severity_answer(report, user_text)
        async for event in self._emit_text_answer(
            ans, f"[FastPath] severity_query={sq}"
        ):
            yield event

    # ── Tool handlers ─────────────────────────────────────────────────────────

    async def _handle_generate_message(self, intent_result, session):
        clause_ids = list(intent_result.target_clause_ids)
        if not clause_ids and session.active_clause_id:
            clause_ids = [session.active_clause_id]

        if not clause_ids or not session.risk_report:
            yield {
                "type": "sentence",
                "text": (
                    "Please select a specific risk clause first, "
                    "then ask me to write the message."
                ),
            }
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        message_type = intent_result.message_type or "clarification"
        tone = intent_result.tone or "professional"
        fmt = intent_result.format or "email"
        extra_instruction = getattr(intent_result, "extra_instruction", None)

        yield {"type": "status", "state": "tool_running", "label": "Writing your message..."}
        yield {
            "type": "debug",
            "log": (
                f"[GenerateMessageTool] type={message_type} tone={tone} "
                f"format={fmt} clauses={clause_ids}"
                + (f" extra='{extra_instruction}'" if extra_instruction else "")
            ),
        }

        risks = session.risk_report.get("risks", [])
        risk_map = {r["id"]: r for r in risks}
        valid_ids = [cid for cid in clause_ids if cid in risk_map]

        if not valid_ids:
            yield {
                "type": "sentence",
                "text": (
                    "I couldn't find the referenced clause in your report. "
                    "Please check the risk IDs."
                ),
            }
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        selected = [risk_map[cid] for cid in valid_ids]
        clause_texts = [r.get("clause_text", "") for r in selected]
        risk_titles = [
            f"{r['title']}: {r.get('simple_explanation', '')}" for r in selected
        ]

        from protectme_agent.tools.generate_message_tool import GenerateMessageTool

        tool = GenerateMessageTool()
        try:
            draft = await tool.execute(
                clause_texts=clause_texts,
                risk_titles=risk_titles,
                message_type=message_type,
                tone=tone,
                format=fmt,
                gemini_client=self._client,
                extra_instruction=extra_instruction,
            )
        except Exception as exc:
            logger.error("GenerateMessageTool failed: %s", exc)
            yield {"type": "error", "message": "Failed to generate the message. Please try again."}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        yield {
            "type": "tool_result",
            "tool": "generate_message",
            "result": {
                "clause_ids": valid_ids,
                "message_type": message_type,
                "tone": tone,
                "format": fmt,
            },
        }
        yield {"type": "draft_ready", "draft": draft, "clause_ids": valid_ids}
        yield {"type": "status", "state": "draft_ready", "label": "Your draft is ready."}

    async def _handle_explain_clause(self, intent_result, session):
        clause_ids = list(intent_result.target_clause_ids)
        if not clause_ids and session.active_clause_id:
            clause_ids = [session.active_clause_id]

        yield {"type": "status", "state": "tool_running", "label": "Explaining the clause..."}

        if not clause_ids or not session.risk_report:
            async for event in self._handle_general(
                "The user wants an explanation but no specific clause is selected.", session
            ):
                yield event
            return

        risks = session.risk_report.get("risks", [])
        risk_map = {r["id"]: r for r in risks}
        risk = risk_map.get(clause_ids[0])

        if not risk:
            yield {
                "type": "sentence",
                "text": "I couldn't find that clause in the report. Please select a specific risk.",
            }
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        yield {"type": "debug", "log": f"[ExplainClauseTool] clause={clause_ids[0]}"}

        from protectme_agent.tools.explain_clause_tool import ExplainClauseTool

        tool = ExplainClauseTool()
        try:
            explanation = await tool.execute(
                clause_text=risk.get("clause_text", ""),
                risk_context=risk,
                gemini_client=self._client,
            )
        except Exception as exc:
            logger.error("ExplainClauseTool failed: %s", exc)
            yield {"type": "error", "message": "Failed to explain the clause. Please try again."}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        from protectme_agent.streaming.sentence_buffer import SentenceBuffer

        buf = SentenceBuffer()
        for sentence in buf.add_token(explanation):
            yield {"type": "sentence", "text": sentence}
        for sentence in buf.flush():
            yield {"type": "sentence", "text": sentence}

        yield {"type": "status", "state": "idle", "label": "Ready"}

    async def _handle_generate_questions(self, intent_result, session):
        yield {"type": "status", "state": "tool_running", "label": "Generating questions..."}

        if not session.risk_report:
            yield {
                "type": "sentence",
                "text": "No contract has been analyzed yet. Please upload a contract first.",
            }
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        clause_ids = list(intent_result.target_clause_ids)
        risks = session.risk_report.get("risks", [])
        risk_map = {r["id"]: r for r in risks}

        clause_texts = None
        if clause_ids:
            texts = [risk_map[cid].get("clause_text", "") for cid in clause_ids if cid in risk_map]
            clause_texts = texts or None

        from protectme_agent.tools.generate_questions_tool import GenerateQuestionsTool

        tool = GenerateQuestionsTool()
        try:
            questions = await tool.execute(
                risk_report=session.risk_report if not clause_texts else None,
                clause_texts=clause_texts,
                gemini_client=self._client,
            )
        except Exception as exc:
            logger.error("GenerateQuestionsTool failed: %s", exc)
            yield {"type": "error", "message": "Failed to generate questions. Please try again."}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        yield {"type": "debug", "log": f"[GenerateQuestionsTool] {len(questions)} questions"}
        yield {"type": "sentence", "text": "Here are the questions I suggest asking:"}
        for q in questions:
            yield {"type": "sentence", "text": q}
        yield {"type": "status", "state": "idle", "label": "Ready"}

    async def _stream_gemini_answer(self, prompt: str, session, extra_system: str = ""):
        """Stream a SHORT Gemini answer (fastest model) grounded in the risk_report.
        Tries Flash-Lite first, falls back to the conversation model if unavailable.
        Shared by general Q&A, recommendation, and Arabic handlers."""
        from protectme_agent.streaming.sentence_buffer import SentenceBuffer

        system = self._build_system_prompt(session)
        if extra_system:
            system = f"{system}\n\n{extra_system}"

        primary = getattr(self._client, "voice_fallback_model", None) or self._client.conversation_model
        fallback = self._client.conversation_model
        models_to_try = [primary] + ([fallback] if fallback and fallback != primary else [])

        yield {"type": "debug", "log": f"[VoiceFallback] model={primary} (short answer)"}

        last_exc = None
        for attempt, model_name in enumerate(models_to_try):
            buf = SentenceBuffer()
            produced = False
            try:
                async for chunk in self._client.stream(
                    prompt=prompt,
                    system=system,
                    model=model_name,
                    temperature=0.2,
                ):
                    for sentence in buf.add_token(chunk):
                        produced = True
                        yield {"type": "sentence", "text": sentence}
                for sentence in buf.flush():
                    produced = True
                    yield {"type": "sentence", "text": sentence}
                yield {"type": "status", "state": "idle", "label": "Ready"}
                return
            except Exception as exc:  # model unavailable / transient — try next
                last_exc = exc
                logger.warning("Voice fallback model %s failed: %s", model_name, exc)
                if produced:
                    break
                if attempt == 0:
                    yield {"type": "debug", "log": f"[VoiceFallback] {model_name} failed, retrying with {fallback}"}

        logger.error("Gemini stream error (all models): %s", last_exc)
        yield {"type": "error", "message": "Failed to generate a response. Please try again."}
        yield {"type": "status", "state": "idle", "label": "Ready"}

    async def _handle_general(self, user_text: str, session):
        """General Q&A — short, grounded answer (used when no fast path / tool matched)."""
        async for event in self._stream_gemini_answer(user_text, session):
            yield event

    async def _handle_recommendation(self, user_text: str, session):
        """Situational recommendation — direct & contextual, but never legal certainty."""
        yield {"type": "debug", "log": "[Recommendation] careful contextual answer"}
        extra = (
            "The user is asking for a recommendation about their situation. Give a "
            "direct, practical recommendation in 2 to 4 short sentences, grounded in "
            "the report above. Use CAREFUL language, never legal certainty: prefer "
            "phrasings like 'Based on this contract text…', 'Usually, if you haven't "
            "signed, the contract may not bind you yet, but confirm in writing', and "
            "'I recommend asking for written confirmation before walking away.' "
            "Do not say you are an AI and do not tell the user to consult the report."
        )
        async for event in self._stream_gemini_answer(user_text, session, extra):
            yield event

    # ── Arabic (Phase 8H) ─────────────────────────────────────────────────────

    async def _handle_arabic_routed(self, user_text: str, session):
        """Answer Arabic (or 'explain in Arabic') questions. Detects the same
        fast-path intent (English or Arabic phrasing), then answers in Arabic:
          • generate_message → real draft tool, written in Arabic, format respected
          • biggest/explain/sign/ask → ONE fast flash-lite call, focused on the
            exact risk_report data for that intent (the analyzed report is in
            English, so a single fast call renders it in fluent Arabic)
          • anything else → general Arabic answer grounded in the report
        No intent-router round-trip; always the fast voice_fallback_model."""
        from protectme_agent import fast_path as fp

        key = fp.match_fast_path(user_text) or fp.match_arabic_intent(user_text)
        yield {"type": "debug", "log": f"[Arabic] lang=ar intent={key or 'general'}"}

        # Generate an Arabic message draft (needs a focused clause, like English).
        if key == fp.GENERATE_MESSAGE and session.active_clause_id:
            fmt = fp.detect_message_format(user_text)
            extra_bits = ["Write the entire message in Arabic (العربية)."]
            mi = fp.message_extra_instruction(user_text)
            if mi:
                extra_bits.append(mi)
            intent = _FastIntent(format=fmt, extra_instruction=" ".join(extra_bits))
            async for event in self._handle_generate_message(intent, session):
                yield event
            return

        extra = self._arabic_extra_system(key, session)
        async for event in self._stream_gemini_answer(user_text, session, extra):
            yield event

    def _arabic_extra_system(self, key, session) -> str:
        """Arabic system instruction + a focus directive for the detected intent."""
        from protectme_agent import fast_path as fp

        base = (
            "أجب باللغة العربية الفصحى البسيطة والواضحة فقط. استخدم تقرير المخاطر "
            "الموجود أعلاه، ولا تطلب من المستخدم ذكر أو مشاركة المخاطر — فالتقرير لديك. "
            "اجعل الإجابة من جملتين إلى خمس جمل قصيرة بأسلوب محادثة، بدون فقرات طويلة "
            "أو مصطلحات قانونية معقدة، ولا تستخدم كلمات إنجليزية."
        )
        if key == fp.BIGGEST_RISK:
            focus = " ركّز على أخطر بند (الأعلى خطورة) في التقرير واشرح باختصار لماذا هو مهم."
        elif key == fp.SHOULD_I_SIGN:
            focus = (
                " بناءً على التوصية النهائية ومستوى الخطورة في التقرير، انصح المستخدم "
                "هل يوقّع الآن أم لا، بحذر ودون قطعية قانونية، واقترح طلب تأكيد كتابي."
            )
        elif key == fp.WHAT_TO_ASK:
            focus = " اقترح سؤالاً أو سؤالين مناسبين يطرحهما المستخدم قبل التوقيع، مأخوذة من التقرير."
        elif key == fp.EXPLAIN_CLAUSE and session.active_clause_id:
            focus = (
                " ركّز فقط على البند المحدد حالياً: اشرح معناه ببساطة، ثم لماذا يهم، "
                "ثم سؤال واحد مناسب يطرحه المستخدم قبل التوقيع."
            )
        else:
            focus = ""
        return base + focus

    async def _handle_modify_message(self, user_text: str, session):
        """Modify the most recent generated draft (shorter/formal/firmer/…) and
        emit an updated draft_ready. Does NOT re-explain the clause."""
        from protectme_agent import fast_path as fp

        drafts = getattr(session, "generated_messages", None) or []
        last = drafts[-1]
        # GeneratedMessage may be a pydantic model or a dict depending on caller.
        def _g(obj, key, default=""):
            return getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key, default)
        prev_draft = _g(last, "draft", "") or ""
        clause_ids = list(_g(last, "clause_ids", []) or [])
        message_type = _g(last, "message_type", "clarification") or "clarification"
        tone = _g(last, "tone", "professional") or "professional"
        fmt = _g(last, "format", "email") or "email"

        if not prev_draft:
            # Nothing to modify — fall back to a normal answer.
            async for event in self._handle_general(user_text, session):
                yield event
            return

        yield {"type": "status", "state": "tool_running", "label": "Updating your message..."}
        yield {"type": "debug", "log": f"[ModifyMessage] revising last draft ({len(prev_draft)} chars): {user_text[:60]}"}

        prompt = (
            "Revise the message below according to the user's instruction. "
            "Return ONLY the revised message, no preamble or commentary. "
            "Keep any placeholders like [Your Name]. Keep it professional and polite.\n\n"
            f"User instruction: {user_text}\n\n"
            f"Message to revise:\n{prev_draft}"
        )
        try:
            revised = await self._client.generate(
                prompt=prompt,
                system="You are an expert at concise, professional message editing.",
                model=getattr(self._client, "voice_fallback_model", None) or self._client.conversation_model,
                temperature=0.3,
            )
            revised = (revised or "").strip()
        except Exception as exc:
            logger.error("ModifyMessage failed: %s", exc)
            yield {"type": "error", "message": "Failed to update the message. Please try again."}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        if not revised:
            yield {"type": "error", "message": "Failed to update the message. Please try again."}
            yield {"type": "status", "state": "idle", "label": "Ready"}
            return

        # Spoken confirmation + updated draft. The tool_result lets VoiceService
        # persist the revised draft as the new "latest" (so further tweaks chain).
        yield {"type": "sentence", "text": fp.modify_confirmation(user_text)}
        yield {
            "type": "tool_result",
            "tool": "generate_message",
            "result": {
                "clause_ids": clause_ids,
                "message_type": message_type,
                "tone": tone,
                "format": fmt,
            },
        }
        yield {"type": "draft_ready", "draft": revised, "clause_ids": clause_ids}
        yield {"type": "status", "state": "draft_ready", "label": "Your updated draft is ready."}

    def _build_system_prompt(self, session) -> str:
        from protectme_agent.safety.legal_disclaimer import DISCLAIMER_SHORT

        parts = [
            "You are ProtectMe AI, a contract-risk voice assistant (NOT a lawyer).",
            f"Constraint: {DISCLAIMER_SHORT}",
            "Answer in 2 to 5 short, clear sentences. Use 5 only when the user asks "
            "for more explanation or advice; otherwise keep it to 2 or 3. Be direct "
            "and conversational — this is spoken aloud. Keep each sentence simple and "
            "voice-friendly. Do not produce long legal paragraphs or lists.",
        ]

        rr = session.risk_report or {}
        if rr:
            contract_type = rr.get("contract_type", "a contract")
            overall_risk = rr.get("overall_risk", "unknown")
            recommendation = rr.get("final_recommendation", "Review carefully")
            risks = rr.get("risks", [])

            # Rank risks by severity so the most important appear first/most.
            order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            ranked = sorted(risks, key=lambda r: order.get(r.get("severity", "Medium"), 9))

            # Severity breakdown so the model NEVER claims a severity has no items
            # when the report actually contains them.
            counts: dict[str, int] = {}
            for r in risks:
                sev = r.get("severity", "Medium")
                counts[sev] = counts.get(sev, 0) + 1
            breakdown = ", ".join(
                f"{counts[s]} {s}" for s in ("Critical", "High", "Medium", "Low") if counts.get(s)
            )

            lines = [
                "",
                "=== ANALYZED RISK REPORT (your source of truth) ===",
                f"Contract type: {contract_type}",
                f"Overall risk: {overall_risk}",
                f"Final recommendation: {recommendation}",
                f"Total risks identified: {len(risks)}",
                f"Severity breakdown: {breakdown or 'none'}",
                "All risks (severity-ranked):",
            ]
            # List ALL risks (every severity) so low/medium queries are answerable.
            for r in ranked[:12]:
                lines.append(
                    f"  - [{r.get('severity', '?')}] {r.get('title', 'Risk')}: "
                    f"{r.get('why_it_matters') or r.get('simple_explanation') or ''}"
                )

            if session.active_clause_id:
                active = next((r for r in risks if r.get("id") == session.active_clause_id), None)
                if active:
                    lines.append(
                        f"Currently focused clause ({session.active_clause_id}): "
                        f"\"{active.get('title', '')}\" — {active.get('simple_explanation', '')}"
                    )

            rec_qs = [q for q in rr.get("recommended_questions", []) if q][:3]
            if rec_qs:
                lines.append("Recommended questions: " + " | ".join(rec_qs))

            lines.append("=== END REPORT ===")
            lines.append(
                "IMPORTANT: You ALREADY HAVE the analyzed risk report above. "
                "NEVER ask the user to share, paste, or list the risks — you have them. "
                "Always answer using this report and the focused clause when present."
            )
            parts.append("\n".join(lines))

        parts.append("Do not give legal advice.")
        return "\n".join(parts)
