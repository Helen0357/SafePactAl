"""
Phase 8I follow-up — language-aware drafts + Arabic PDF voice command.

  • REST /api/actions/generate-message honors X-Language: ar → Arabic draft directive
    (chosen format + user custom details still respected)
  • REST default / X-Language: en → no Arabic directive (English unchanged)
  • Arabic download/report/file phrases trigger the download_pdf event (no Gemini)
  • "هل يمكنك ان تقوم بتنزيل الملف" triggers download_pdf, in Arabic
  • English "download the PDF" still triggers download_pdf

Gemini mocked — fast, no quota.
"""
import asyncio
import itertools
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# tests/ → backend/ → protectme-ai-agent/ → agent/
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import Session

client = TestClient(app)

REPORT = {
    "contract_type": "Rental Agreement",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "Risky.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "Deposit Forfeiture", "severity": "High",
         "category": "Deposit", "clause_text": "Forfeit deposit.",
         "simple_explanation": "You lose your deposit.", "why_it_matters": "Costly.",
         "question_to_ask": "Pro-rate?", "suggested_action": "Negotiate"},
    ],
    "missing_information": [], "recommended_questions": [],
}


def _make_session() -> str:
    s = Session(risk_report=REPORT, contract_text="x")
    session_repository.create(s)
    return s.session_id


def _mock_gemini(draft_text: str = "مسودة عربية."):
    mock = MagicMock()
    mock.conversation_model = "gemini-3.5-flash"
    mock.generate = AsyncMock(return_value=draft_text)
    return mock


def _mock_gemini_sequence(*drafts: str):
    """Mock whose generate() returns each draft in turn (for retry tests)."""
    mock = MagicMock()
    mock.conversation_model = "gemini-3.5-flash"
    mock.generate = AsyncMock(side_effect=list(drafts))
    return mock


def _contains_arabic(text: str) -> bool:
    """True if the text has any Arabic character (test-side mirror of _has_arabic)."""
    return any("؀" <= ch <= "ۿ" for ch in (text or ""))


# ── REST generate-message X-Language (Issue 1) ─────────────────────────────────

class TestGenerateMessageLanguage:
    """The X-Language header drives the language of the generated draft."""

    def _post(self, sid, mock_client, headers=None, **body_overrides):
        body = {
            "session_id": sid,
            "clause_ids": ["risk_001"],
            "message_type": "clarification",
            "tone": "polite",
            "format": "email",
        }
        body.update(body_overrides)
        with patch("app.services.message_service._build_gemini_client",
                   return_value=mock_client):
            return client.post("/api/actions/generate-message",
                               json=body, headers=headers or {})

    def test_arabic_header_adds_arabic_directive(self):
        mock_client = _mock_gemini()
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" in prompt              # Arabic directive present
        assert "LANGUAGE REQUIREMENT" in prompt # strong, prominent directive
        assert "الموضوع:" in prompt             # Arabic subject label, not "Subject:"
        assert "email" in prompt.lower()        # chosen format still respected

    def test_arabic_email_format_uses_arabic_subject_label(self):
        # Arabic + email: the prompt must steer the subject to "الموضوع:" (not English).
        mock_client = _mock_gemini()
        resp = self._post(_make_session(), mock_client,
                          headers={"X-Language": "ar"}, format="email")
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "الموضوع:" in prompt
        assert "البريد الإلكتروني" in prompt  # localized email guideline

    def test_arabic_whatsapp_format_is_arabic(self):
        # Arabic + WhatsApp: localized WhatsApp guideline + Arabic directive.
        mock_client = _mock_gemini()
        resp = self._post(_make_session(), mock_client,
                          headers={"X-Language": "ar"}, format="whatsapp")
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" in prompt
        assert "واتساب" in prompt             # localized WhatsApp guideline
        assert "whatsapp" in prompt.lower()   # chosen format still respected

    def test_arabic_header_preserves_custom_details(self):
        mock_client = _mock_gemini()
        resp = self._post(
            _make_session(), mock_client, headers={"X-Language": "ar"},
            format="whatsapp",
            extra_instruction="Mention my move-in date is July 1.",
        )
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" in prompt           # Arabic directive present
        assert "July 1" in prompt            # user's custom detail preserved
        assert "whatsapp" in prompt.lower()  # chosen format still respected

    def test_english_default_has_no_arabic_directive(self):
        mock_client = _mock_gemini("English draft.")
        resp = self._post(_make_session(), mock_client)  # no X-Language header
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" not in prompt          # English unchanged
        assert "LANGUAGE REQUIREMENT" not in prompt
        assert "Subject line" in prompt         # English format guideline intact

    def test_english_header_has_no_arabic_directive(self):
        mock_client = _mock_gemini("English draft.")
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "en"})
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" not in prompt

    def test_arabic_english_draft_triggers_one_retry(self):
        # Model returns an English "Subject:" draft first → service retries once and
        # the Arabic second attempt wins. (Acceptance: no English "Subject:" survives.)
        mock_client = _mock_gemini_sequence(
            "Subject: Clarification Request\n\nDear Landlord, ...",
            "الموضوع: طلب توضيح\n\nمرحباً، أود الاستفسار عن بنود العقد ...",
        )
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert mock_client.generate.await_count == 2          # retried exactly once
        draft = resp.json()["draft"]
        assert "الموضوع:" in draft and "Subject:" not in draft  # Arabic draft won

    def test_arabic_draft_already_arabic_no_retry(self):
        # Model returns Arabic on the first attempt → no wasteful retry.
        mock_client = _mock_gemini("الموضوع: طلب توضيح\n\nمرحباً ...")
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert mock_client.generate.await_count == 1

    def test_english_never_retries(self):
        # English draft for an English request must not trigger the Arabic retry.
        mock_client = _mock_gemini("Subject: Clarification Request\n\nDear Landlord, ...")
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "en"})
        assert resp.status_code == 200
        assert mock_client.generate.await_count == 1


# ── Prompt builder + Arabic-detection units ────────────────────────────────────

class TestPromptBuilderLanguage:
    def test_build_prompt_arabic_vs_english(self):
        from protectme_agent.prompts.message_generation_prompt import build_message_prompt
        ar = build_message_prompt(
            risk_summaries=["Deposit"], clause_texts=["x"],
            message_type="clarification", tone="polite", format="email",
            language="ar",
        )
        en = build_message_prompt(
            risk_summaries=["Deposit"], clause_texts=["x"],
            message_type="clarification", tone="polite", format="email",
            language="en",
        )
        assert "العربية" in ar and "الموضوع:" in ar
        assert "العربية" not in en and "Subject line" in en

    def test_has_arabic_helper(self):
        from app.services.message_service import _has_arabic
        assert _has_arabic("مرحباً")
        assert _has_arabic("الموضوع: طلب")
        assert not _has_arabic("Subject: Clarification Request")
        assert not _has_arabic("")

    def test_is_acceptable_arabic_rejects_english_markers(self):
        from app.services.message_service import _is_acceptable_arabic
        # Arabic but with English scaffolding leaking in → not acceptable.
        assert not _is_acceptable_arabic("Subject: طلب\n\nمرحباً")
        assert not _is_acceptable_arabic("مرحباً\nDear Landlord")
        assert not _is_acceptable_arabic("English only, no Arabic.")
        # Clean Arabic (English name placeholders are allowed) → acceptable.
        assert _is_acceptable_arabic("الموضوع: طلب توضيح\n\nمرحباً [اسم المستلم]،")


# ── Real dashboard request: Arabic output is guaranteed (Issue, attempt 3) ─────
# An English report content + Arabic UI must still yield an Arabic draft, even if
# the model returns English — the deterministic fallback enforces it.

AR_REPORT = {
    "contract_type": "اتفاقية إيجار",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "بنود مجحفة.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "مصادرة الوديعة", "severity": "High",
         "category": "Deposit", "clause_text": "مصادرة الوديعة.",
         "simple_explanation": "تفقد وديعتك.", "why_it_matters": "مكلف.",
         "question_to_ask": "هل يمكن التقسيط؟", "suggested_action": "تفاوض"},
    ],
    "missing_information": [], "recommended_questions": [],
}


def _make_ar_report_session() -> str:
    s = Session(risk_report=AR_REPORT, contract_text="عقد")
    session_repository.create(s)
    return s.session_id


def _post_generate(sid, mock_client, headers=None, **body_overrides):
    body = {
        "session_id": sid,
        "clause_ids": ["risk_001"],
        "message_type": "clarification",
        "tone": "polite",
        "format": "email",
    }
    body.update(body_overrides)
    with patch("app.services.message_service._build_gemini_client",
               return_value=mock_client):
        return client.post("/api/actions/generate-message",
                           json=body, headers=headers or {})


_EN_EMAIL = "Subject: Clarification Request\n\nDear Landlord,\nI hope this email finds you well.\n\nBest regards,\n[Your Name]"


class TestArabicOutputGuarantee:
    def test_arabic_email_output_is_arabic_even_if_model_returns_english(self):
        # Model returns English twice → deterministic Arabic email fallback.
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client,
                              headers={"X-Language": "ar"}, format="email")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert _contains_arabic(draft)        # output is Arabic
        assert "الموضوع:" in draft            # Arabic subject label
        assert "Subject:" not in draft        # no English subject
        assert "Dear" not in draft            # no English greeting
        assert "Best regards" not in draft    # no English closing
        assert mock_client.generate.await_count == 2  # tried + retried, then fallback

    def test_arabic_whatsapp_output_is_arabic_no_subject(self):
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client,
                              headers={"X-Language": "ar"}, format="whatsapp")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert _contains_arabic(draft)
        assert "Subject:" not in draft and "الموضوع:" not in draft  # no subject line
        assert "Dear" not in draft

    def test_arabic_email_passthrough_when_model_returns_arabic(self):
        # Good Arabic from the model is returned as-is (no fallback, no extra calls).
        good = "الموضوع: طلب توضيح\n\nمرحباً [اسم المستلم]،\nأود الاستفسار...\n\nمع خالص التحية،\n[اسمك]"
        mock_client = _mock_gemini(good)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert resp.json()["draft"] == good
        assert mock_client.generate.await_count == 1

    def test_english_email_output_is_english(self):
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client,
                              headers={"X-Language": "en"}, format="email")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert draft == _EN_EMAIL          # English structure allowed, unchanged
        assert mock_client.generate.await_count == 1  # never retries for English

    def test_arabic_ui_english_contract_outputs_arabic(self):
        # English report content + Arabic UI → Arabic draft (website language wins).
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert _contains_arabic(resp.json()["draft"])

    def test_english_ui_arabic_contract_outputs_english(self):
        # Arabic report content + English UI → English draft (website language wins).
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_ar_report_session(), mock_client,
                              headers={"X-Language": "en"})
        assert resp.status_code == 200
        assert resp.json()["draft"] == _EN_EMAIL
        assert mock_client.generate.await_count == 1  # no Arabic forcing

    def test_arabic_custom_detail_preserved_in_prompt_and_output(self):
        good = "الموضوع: طلب توضيح\n\nمرحباً،\nلدي أسد في المنزل ولذلك...\n\nمع خالص التحية،"
        mock_client = _mock_gemini(good)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              extra_instruction="لدي أسد")
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "أسد" in prompt                 # custom detail reached the model
        assert "أسد" in resp.json()["draft"]   # and survives in the output

    def test_arabic_custom_detail_preserved_in_fallback(self):
        # Even the deterministic fallback keeps the user's custom detail.
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              extra_instruction="لدي أسد")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert _contains_arabic(draft) and "أسد" in draft

    def test_english_custom_detail_preserved(self):
        mock_client = _mock_gemini("Subject: Inquiry\n\nDear Landlord, I have a lion at home...")
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "en"},
                              extra_instruction="I have a lion")
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "I have a lion" in prompt
        assert "lion" in resp.json()["draft"]


# ── Full 24-combination matrix: every Arabic combination yields Arabic ─────────
# 4 message types × 3 tones × 2 formats. Worst case: the model returns an English
# email for EVERY combination — the backend must still return an Arabic draft.

_TYPES = ["clarification", "negotiation", "rejection", "amendment_request"]
_TONES = ["polite", "firm", "professional"]
_FORMATS = ["email", "whatsapp"]
_COMBOS = list(itertools.product(_TYPES, _TONES, _FORMATS))


class TestArabicCombinationMatrix:
    @pytest.mark.parametrize("mtype,tone,fmt", _COMBOS)
    def test_arabic_combo_yields_arabic_even_if_model_english(self, mtype, tone, fmt):
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)  # model fails twice
        resp = _post_generate(
            _make_session(), mock_client, headers={"X-Language": "ar"},
            message_type=mtype, tone=tone, format=fmt,
        )
        assert resp.status_code == 200, f"{mtype}/{tone}/{fmt} -> {resp.status_code}"
        draft = resp.json()["draft"]
        assert _contains_arabic(draft), f"{mtype}/{tone}/{fmt} not Arabic"
        assert "Subject:" not in draft
        assert "Dear" not in draft
        assert "Best regards" not in draft
        if fmt == "email":
            assert "الموضوع:" in draft          # Arabic subject label
        else:
            assert "الموضوع:" not in draft       # WhatsApp has no subject line

    @pytest.mark.parametrize("mtype,tone,fmt", _COMBOS)
    def test_arabic_combo_passthrough_when_model_arabic(self, mtype, tone, fmt):
        good = "الموضوع: طلب\n\nمرحباً [اسم المستلم]،\nأود الاستفسار بخصوص بنود العقد.\n\nمع خالص التحية،\n[اسمك]"
        mock_client = _mock_gemini(good)
        resp = _post_generate(
            _make_session(), mock_client, headers={"X-Language": "ar"},
            message_type=mtype, tone=tone, format=fmt,
        )
        assert resp.status_code == 200
        assert resp.json()["draft"] == good            # good Arabic returned as-is
        assert mock_client.generate.await_count == 1    # no wasteful retry

    @pytest.mark.parametrize("mtype,tone,fmt", _COMBOS)
    def test_english_combo_regression(self, mtype, tone, fmt):
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(
            _make_session(), mock_client, headers={"X-Language": "en"},
            message_type=mtype, tone=tone, format=fmt,
        )
        assert resp.status_code == 200
        assert resp.json()["draft"] == _EN_EMAIL       # English unchanged
        assert mock_client.generate.await_count == 1    # never retries for English


# ── Backend defensive normalization of message option values ───────────────────

class TestOptionNormalization:
    @pytest.mark.parametrize("arabic,canonical", [
        ("استفسار", "clarification"),
        ("تفاوض", "negotiation"),
        ("رفض", "rejection"),
        ("تعديل", "amendment_request"),
    ])
    def test_arabic_message_type_label_normalized(self, arabic, canonical):
        mock_client = _mock_gemini("الموضوع: طلب\n\nمرحباً،\nنص.\n\nمع خالص التحية،")
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              message_type=arabic)
        assert resp.status_code == 200
        assert resp.json()["message_type"] == canonical

    @pytest.mark.parametrize("arabic,canonical", [
        ("لطيف", "polite"), ("حازم", "firm"), ("رسمي", "professional"),
    ])
    def test_arabic_tone_label_normalized(self, arabic, canonical):
        mock_client = _mock_gemini("الموضوع: طلب\n\nمرحباً،\nنص.\n\nمع خالص التحية،")
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              tone=arabic)
        assert resp.status_code == 200
        assert resp.json()["tone"] == canonical

    @pytest.mark.parametrize("arabic,canonical", [
        ("بريد", "email"), ("إيميل", "email"), ("واتساب", "whatsapp"), ("رسالة", "whatsapp"),
    ])
    def test_arabic_format_label_normalized(self, arabic, canonical):
        mock_client = _mock_gemini("الموضوع: طلب\n\nمرحباً،\nنص.\n\nمع خالص التحية،")
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              format=arabic)
        assert resp.status_code == 200
        assert resp.json()["format"] == canonical

    def test_english_canonical_values_unchanged(self):
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "en"},
                              message_type="negotiation", tone="firm", format="whatsapp")
        assert resp.status_code == 200
        body = resp.json()
        assert body["message_type"] == "negotiation"
        assert body["tone"] == "firm"
        assert body["format"] == "whatsapp"

    def test_english_display_label_aliases_normalized(self):
        # Defensive: even English display labels ("Clarify"/"Pro") map to canonical.
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "en"},
                              message_type="Clarify", tone="Pro", format="Email")
        assert resp.status_code == 200
        body = resp.json()
        assert body["message_type"] == "clarification"
        assert body["tone"] == "professional"
        assert body["format"] == "email"

    def test_unknown_value_still_rejected(self):
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "en"},
                              message_type="totally_invalid")
        assert resp.status_code == 422  # unknown values still fail enum validation


# ── Language resolution: body > header > session > default ─────────────────────
# The request BODY 'language' is the primary, reliable channel (the X-Language
# header can be stripped or lag during navigation in the real browser).

def _make_session_lang(lang) -> str:
    s = Session(risk_report=REPORT, contract_text="x", language=lang)
    session_repository.create(s)
    return s.session_id


class TestLanguageResolution:
    def test_resolve_priority_unit(self):
        from app.services.message_service import _resolve_language as r
        assert r("ar", None, None) == ("ar", "body")
        assert r("en", "ar", "ar") == ("en", "body")     # body wins over header/session
        assert r(None, "ar", None) == ("ar", "header")
        assert r(None, None, "ar") == ("ar", "session")
        assert r(None, None, None) == ("en", "default")
        assert r("", "", "") == ("en", "default")          # blanks skipped
        assert r("AR-SA", None, None) == ("ar", "body")     # clamped to ar

    def test_body_language_ar_email_yields_arabic(self):
        # No header at all — body language=ar must still produce Arabic.
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, language="ar", format="email")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert _contains_arabic(draft) and "الموضوع:" in draft
        assert "Subject:" not in draft

    def test_body_language_ar_whatsapp_yields_arabic(self):
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, language="ar", format="whatsapp")
        assert resp.status_code == 200
        draft = resp.json()["draft"]
        assert _contains_arabic(draft) and "الموضوع:" not in draft

    def test_header_only_ar_still_works(self):
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert _contains_arabic(resp.json()["draft"])

    def test_body_overrides_header(self):
        # body=ar beats header=en → Arabic.
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "en"},
                              language="ar")
        assert resp.status_code == 200
        assert _contains_arabic(resp.json()["draft"])

    def test_body_en_overrides_header_ar(self):
        # body=en beats header=ar → English (returned unchanged, no retry).
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, headers={"X-Language": "ar"},
                              language="en")
        assert resp.status_code == 200
        assert resp.json()["draft"] == _EN_EMAIL
        assert mock_client.generate.await_count == 1

    def test_session_language_fallback_ar(self):
        # No body, no header — falls back to the session language (ar).
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session_lang("ar"), mock_client)
        assert resp.status_code == 200
        assert _contains_arabic(resp.json()["draft"])

    def test_default_english_when_nothing_set(self):
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_session_lang("en"), mock_client)
        assert resp.status_code == 200
        assert resp.json()["draft"] == _EN_EMAIL

    def test_arabic_ui_english_contract_body(self):
        # Arabic UI (body=ar) + English contract content → Arabic draft.
        mock_client = _mock_gemini_sequence(_EN_EMAIL, _EN_EMAIL)
        resp = _post_generate(_make_session(), mock_client, language="ar")
        assert resp.status_code == 200
        assert _contains_arabic(resp.json()["draft"])

    def test_english_ui_arabic_contract_body(self):
        # English UI (body=en) + Arabic contract content → English draft.
        mock_client = _mock_gemini(_EN_EMAIL)
        resp = _post_generate(_make_ar_report_session(), mock_client, language="en")
        assert resp.status_code == 200
        assert resp.json()["draft"] == _EN_EMAIL
        assert mock_client.generate.await_count == 1


# ── Arabic PDF voice command → download_pdf event (Issue 2) ────────────────────

class TestArabicPdfVoiceCommand:
    def test_wants_pdf_arabic_phrases(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in [
            "تنزيل الملف", "تحميل الملف", "نزل الملف", "حمل الملف",
            "حمّل الملف", "نزّل الملف", "تنزيل التقرير", "تحميل التقرير",
            "حمل التقرير", "نزل التقرير", "صدّر التقرير", "اعمل ملف",
            "اعمل PDF", "ملف PDF", "تقرير PDF", "نزّل PDF", "حمّل PDF",
            "أريد التقرير", "ابغى التقرير",
            "هل يمكنك ان تقوم بتنزيل الملف",
            "ممكن تنزل التقرير", "ارسل لي ملف التقرير",
        ]:
            assert wants_pdf(phrase), f"Arabic phrase should trigger PDF: {phrase}"

    def test_wants_pdf_english_still_works(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in ["download the PDF", "generate a PDF report",
                       "can you export the report", "make me a pdf"]:
            assert wants_pdf(phrase), f"English phrase should trigger PDF: {phrase}"

    def test_wants_pdf_ignores_normal_questions(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in ["what is the biggest risk?", "اشرح لي البند الأول",
                       "should I sign this?", "ما هو أكبر خطر؟"]:
            assert not wants_pdf(phrase), f"Should NOT trigger PDF: {phrase}"

    # ── handle_turn integration (no Gemini needed for the PDF fast path) ──────
    def _mock_client(self):
        mock = MagicMock()
        mock.conversation_model = "gemini-3.5-flash"
        mock.voice_fallback_model = "gemini-3.1-flash-lite"

        async def _stream(*a, **k):
            yield "..."
        mock.stream = _stream
        return mock

    def _run(self, user_text, language="ar"):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT, language=language)

        async def _collect():
            return [e async for e in agent.handle_turn(user_text, session)]

        return asyncio.run(_collect())

    def _said(self, events):
        return " ".join(e["text"] for e in events if e["type"] == "sentence")

    def test_arabic_download_file_triggers_download_event(self):
        events = self._run("تنزيل الملف")
        assert any(e["type"] == "download_pdf" for e in events)

    def test_arabic_polite_question_triggers_download_event(self):
        events = self._run("هل يمكنك ان تقوم بتنزيل الملف")
        assert any(e["type"] == "download_pdf" for e in events)

    def test_arabic_download_message_is_arabic(self):
        events = self._run("حمّل لي تقرير PDF")
        dl = [e for e in events if e["type"] == "download_pdf"]
        assert dl, "expected a download_pdf event"
        # Spoken confirmation is Arabic ("تم تجهيز تقرير PDF لك.")
        assert "تجهيز" in self._said(events)

    def test_english_download_pdf_still_triggers_event(self):
        events = self._run("download the PDF report", language="en")
        assert any(e["type"] == "download_pdf" for e in events)
        assert "PDF" in self._said(events)  # English confirmation
