"""
Fast Smart Path — Phase 8F.

Answers the most common demo questions DIRECTLY from the analyzed risk_report
JSON, with no Gemini call (no intent-router round-trip, no answer generation).
This is not "memorizing" — the risk_report IS the agent's analyzed source of
truth for the loaded contract, so reading from it is both correct and instant.

match_fast_path(user_text) -> one of the fast-path keys, or None.
The build_* functions turn the report into short, voice-friendly answer text.
A return of None means "I can't answer this from the report" → the caller should
fall through to the normal Gemini routing.
"""
import re
from typing import Optional

# Fast-path keys
BIGGEST_RISK     = "biggest_risk"
EXPLAIN_CLAUSE   = "explain_active_clause"
SHOULD_I_SIGN    = "should_i_sign"
WHAT_TO_ASK      = "what_should_i_ask"
GENERATE_MESSAGE = "generate_message"

# Order matters: more specific / unambiguous intents are checked first so that,
# e.g., "write a message about the biggest risk" routes to generate_message.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    (GENERATE_MESSAGE, re.compile(
        r"\b(write|draft|compose|prepare)\b.*\b(message|email|letter|note|whatsapp)\b"
        r"|\b(write me|draft me|send)\b|\bdraft (this|that|it)\b"
        r"|\b(message|email|letter) (to|for|about)\b",
        re.IGNORECASE)),
    (BIGGEST_RISK, re.compile(
        # "biggest/largest/main/top/highest/worst … risk/issue/impact/scale/…"
        r"\b(biggest|largest|main|top|highest|greatest|worst|major)\b"
        r".{0,15}?\b(risk|clause|concern|issue|problem|impact|scale|danger|thing|part)s?\b"
        # "most dangerous / most risky / most serious …"
        r"|\bmost (dangerous|serious|important|concerning|risky|severe|significant)\b"
        # bare common phrasings
        r"|\b(biggest|main|worst|largest) (risk|issue|problem|concern|impact|scale)\b",
        re.IGNORECASE)),
    (SHOULD_I_SIGN, re.compile(
        r"\bshould i sign\b|\b(safe|ok|okay|wise|smart) to sign\b"
        r"|\bcan i sign\b|\bdo i sign\b|\bsign (this|it)\b|\bshould i agree\b",
        re.IGNORECASE)),
    (WHAT_TO_ASK, re.compile(
        r"\bwhat (should|do|can) i ask\b|\bwhat to ask\b"
        r"|\bquestions?\b.{0,20}\b(ask|before signing|raise)\b"
        r"|\bwhat questions\b",
        re.IGNORECASE)),
    (EXPLAIN_CLAUSE, re.compile(
        r"\bexplain (this|it|that|the clause)\b|\bexplain\b"
        r"|\bwhat does (this|it|that) mean\b|\bwhat is this\b"
        r"|\bis (this|it|that) risky\b|\bbreak (this|it) down\b"
        r"|\bwhat('?s| is) the (risk|problem|issue)\b",
        re.IGNORECASE)),
]


def match_fast_path(user_text: str) -> Optional[str]:
    """Return the fast-path key for a common question, or None to use Gemini."""
    t = (user_text or "").strip()
    if not t:
        return None
    for key, pat in _PATTERNS:
        if pat.search(t):
            return key
    return None


# ── Phase 8F-mod: extra deterministic / fast-intent detection ────────────────

# "explain more / easier / I didn't understand / simplify / in detail"
_DETAIL_RE = re.compile(
    r"(explain.*\b(more|again|easier|simpl|further|detail)\b)"
    r"|\b(easier|simpler|simplif(y|ied)|more easy|easy way|in more detail|more detail|"
    r"elaborate|in depth|didn'?t understand|did not understand|don'?t understand|"
    r"do not understand|i don'?t get|not clear|too complicated|too complex|"
    r"break (it|this|that) down|say (it|that) again|repeat that)\b",
    re.IGNORECASE,
)

# Arabic requested explicitly, or the message itself contains Arabic script.
_ARABIC_RE = re.compile(
    r"\b(in arabic|arabic( language| please)?|translate to arabic)\b|[؀-ۿ]",
    re.IGNORECASE,
)

# Modify the latest generated draft.
_MODIFY_RE = re.compile(
    r"\bmake it (much )?(short(er)?|long(er)?|simpler|formal|stronger|polite|firm|"
    r"firmer|better|nicer|clearer|softer|brief(er)?|concise|smaller)\b"
    r"|\b(shorten|lengthen) (it|this|that)\b"
    r"|\b(rewrite|redo|rephrase|improve|revise|change|fix|polish) (it|this|that)\b"
    r"|\bmore (formal|polite|professional|firm|assertive|direct|concise|brief)\b"
    r"|\b(too long|too short|not (good |strong )?enough|make it more)\b"
    r"|\btry again\b|\bdo it again\b|\bi don'?t like (it|this)\b",
    re.IGNORECASE,
)

# Situational recommendation ("should I reject", "am I safe", "can he charge me").
_RECOMMEND_RE = re.compile(
    r"\bshould i (reject|refuse|accept|walk away|back out|negotiate|wait|leave|cancel|push back)\b"
    r"|\bif (he|she|they|the landlord|the other party) (refus|reject|decline|say no|won'?t|do(es)? not)\b"
    r"|\bam i safe\b|\b(can|will|could) (he|she|they) charge( me)?\b"
    r"|\bam i (bound|liable|obligated|committed|protected|stuck)\b"
    r"|\bi (did ?n'?t|have ?n'?t|did not|have not) (sign|pay|paid)\b"
    r"|\b(i'?m |i am )?not satisfied\b|\bwhat are my (options|rights)\b"
    r"|\bwhat should i do\b",
    re.IGNORECASE,
)


def wants_generate(user_text: str) -> bool:
    """True if the user is asking to WRITE a new message/email/etc. Used to keep
    'write a whatsapp message, make it short' from being treated as a draft edit."""
    return match_fast_path(user_text) == GENERATE_MESSAGE


# ── Message format / length parsing (Phase 8-bugfix #3) ──────────────────────
# "write WhatsApp message make it short" was generating an email. Detect the
# requested format and any short/long instruction directly from the user text.
_WHATSAPP_RE = re.compile(
    r"\b(whats ?app|whatsapp|wapp|\bwa\b|text(?: message)?|sms|dm)\b"
    r"|واتساب|واتس|رسالة قصيرة|رساله قصيره",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"\b(e[- ]?mails?|emails?|mail|formal email)\b|ايميل|إيميل|بريد",
    re.IGNORECASE,
)
_SHORT_RE = re.compile(
    r"\b(short|shorter|shortly|brief|briefly|concise|small|tiny|quick|to the point)\b"
    r"|قصير|قصيرة|قصيره|مختصر|مختصرة|موجز|بإيجاز",
    re.IGNORECASE,
)
_LONGER_RE = re.compile(
    r"\b(detailed|in detail|longer|more detail|comprehensive|thorough|elaborate)\b",
    re.IGNORECASE,
)


def detect_message_format(user_text: str) -> Optional[str]:
    """Return 'whatsapp' or 'email' if the user named a channel, else None.
    WhatsApp / text / SMS is checked first so 'whatsapp message' isn't read as email."""
    t = user_text or ""
    if _WHATSAPP_RE.search(t):
        return "whatsapp"
    if _EMAIL_RE.search(t):
        return "email"
    return None


def message_extra_instruction(user_text: str) -> Optional[str]:
    """Turn 'make it short' / 'keep it brief' etc. into a tool instruction."""
    t = user_text or ""
    if _SHORT_RE.search(t):
        return "Make it short and concise."
    if _LONGER_RE.search(t):
        return "Add a bit more detail and context."
    return None


def wants_detail(user_text: str) -> bool:
    return bool(_DETAIL_RE.search(user_text or ""))


def wants_arabic(user_text: str) -> bool:
    return bool(_ARABIC_RE.search(user_text or ""))


def wants_modify(user_text: str) -> bool:
    return bool(_MODIFY_RE.search(user_text or ""))


def is_recommendation(user_text: str) -> bool:
    return bool(_RECOMMEND_RE.search(user_text or ""))


# Refers to the multiple selected clauses ("explain these clauses", "compare
# these", "write a message about these", and Arabic equivalents).
_SELECTED_RE = re.compile(
    r"\bthese (clauses?|two|three|risks?|ones|terms?|selected)\b"
    r"|\bthe(se)? selected (clauses?|risks?|ones)\b"
    r"|\bselected clauses?\b"
    r"|\bboth (clauses?|risks?|of them|of these)\b|\bthese two\b"
    r"|\bcompare (these|them|the (two|clauses|risks))\b"
    r"|\b(about|on) these\b|\btell me about both\b"
    r"|هذين البندين|هذين الشرطين|هذه البنود|البندين المحددين|البنود المحددة"
    r"|كلا البندين|قارن بين|عن هذه البنود|هذين الاثنين",
    re.IGNORECASE,
)


def wants_selected(user_text: str) -> bool:
    return bool(_SELECTED_RE.search(user_text or ""))


# Follow-up phrasings that should REUSE the active selection (only when a
# selection is already in context): pronouns, "explain more/again/easier",
# "what about them", "both", "compare", and Arabic equivalents.
_SELECTED_FOLLOWUP_RE = re.compile(
    r"\b(them|those|they)\b"
    r"|\bexplain (it )?(more|again|further|better)\b"
    r"|\b(easier|simpler|simplify|in (more )?detail|more detail|in depth)\b"
    r"|\bwhat about (them|those|these|both)\b"
    r"|\btell me more\b|\bmore about (them|those|these|both)\b"
    r"|\bboth\b|\bcompare\b"
    r"|اشرحهم|اشرح أكثر|وضح أكثر|بطريقة أسهل|أسهل|ماذا عنهم|كلاهما|كليهما|قارن|اشرح مرة أخرى",
    re.IGNORECASE,
)


def selected_followup(user_text: str) -> bool:
    return bool(_SELECTED_FOLLOWUP_RE.search(user_text or ""))


# ── PDF report download (Phase 8I) ───────────────────────────────────────────
# "download/generate/export the report as a PDF", "make a PDF", "give me a file",
# and Arabic equivalents. Deterministic — triggers a frontend download event.
_PDF_RE = re.compile(
    # English: a download/export verb near pdf/report/file, or bare "pdf".
    r"\b(download|generate|create|export|make|prepare|give me|send me|get me|build)\b"
    r"[^.?!]{0,25}\b(pdf|report|file|document|copy)\b"
    r"|\bpdf\b|\bdownload (the )?report\b|\bexport (the )?report\b"
    # Arabic: a download/export/send verb stem near ملف/تقرير/pdf …
    r"|(?:تنزيل|تحميل|تنزّل|تنزل|ينزل|نزّل|نزل|نزله|حمّل|حمل|حمله|صدّر|صدر|أنزل|انزل"
    r"|ارسل|أرسل|اعمل|سوّي|سوي|عطني|اعطني|أعطني)[^.؟!]{0,15}(?:ملف|تقرير|pdf|بي دي اف)"
    # … or "I want the report/file/pdf" …
    r"|(?:أريد|اريد|ابغى|أبغى|بدي|عايز)[^.؟!]{0,12}(?:التقرير|تقرير|الملف|ملف|pdf)"
    # … or bare "pdf file" / "pdf report" / "the report file".
    r"|ملف\s*pdf|تقرير\s*pdf|ملف التقرير",
    re.IGNORECASE,
)


def wants_pdf(user_text: str) -> bool:
    """True if the user is asking to download/generate a PDF report (EN or AR)."""
    return bool(_PDF_RE.search(user_text or ""))


# ── Per-turn / session language (Phase 8I-i18n) ──────────────────────────────
_ENGLISH_RE = re.compile(
    r"\bin english\b|\benglish (please|language|version)\b|\bspeak english\b"
    r"|\breply in english\b|\banswer in english\b"
    r"|بالانجليزي|بالإنجليزي|بالإنجليزية|بالانجليزية|انجليزي|إنجليزي|بالانكليزي",
    re.IGNORECASE,
)


def wants_english(user_text: str) -> bool:
    return bool(_ENGLISH_RE.search(user_text or ""))


def normalize_language(lang) -> str:
    """Clamp any language value to the allowed set: 'ar' or 'en' (default 'en')."""
    return "ar" if str(lang or "").strip().lower().startswith("ar") else "en"


def resolve_response_language(user_text: str, session_lang: str = "en") -> str:
    """Per-turn response language. An explicit request in the message wins
    ('explain in English' / 'بالعربي'); otherwise use the session/UI language."""
    if wants_english(user_text):
        return "en"
    if wants_arabic(user_text):
        return "ar"
    return normalize_language(session_lang)


# ── Arabic language support (Phase 8H) ───────────────────────────────────────
# Lightweight, per-turn language detection + Arabic intent matching so Arabic
# questions route to the same fast-path intents and answer from the risk_report.

_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")


def detect_language(user_text: str) -> str:
    """Per-turn response language: 'ar' if the text is Arabic OR explicitly asks
    for Arabic ('explain in Arabic', 'بالعربي'); otherwise 'en'."""
    return "ar" if wants_arabic(user_text) else "en"


# Arabic phrasings for each fast-path intent. Arabic has no word boundaries like
# \b, so these match substrings (with common hamza spelling variants).
_AR_PATTERNS: list[tuple[str, re.Pattern]] = [
    (GENERATE_MESSAGE, re.compile(
        r"(اكتب|أكتب|اكتبي|جهّز|جهز|صغ|صياغة|أنشئ|انشئ).{0,18}"
        r"(رسالة|رساله|ايميل|إيميل|بريد|واتساب|واتس|رد|ردا|ردًا)"
        r"|رسالة واتساب|رسالة قصيرة|اكتب رد|اكتب لي")),
    (BIGGEST_RISK, re.compile(
        r"(أكبر|اكبر|أعظم|اعظم|الأكبر).{0,15}(خطر|خطورة|مشكلة|بند|مخاطر|شيء|شي)"
        r"|(أخطر|اخطر).{0,10}(بند|شيء|شي|خطر)"
        r"|(أكثر|اكثر).{0,10}خطورة|الخطر الأكبر")),
    (SHOULD_I_SIGN, re.compile(
        r"هل أوقع|هل اوقع|هل أوقّع|أوقع العقد|اوقع العقد|توقيع العقد"
        r"|هل تنصحني|تنصحني أوقع|تنصحني اوقع|هل العقد آمن|العقد آمن"
        r"|هل أرفض|هل ارفض|أرفض العقد|ارفض العقد|هل أوافق|هل اوافق")),
    (WHAT_TO_ASK, re.compile(
        r"ماذا أسأل|ماذا اسأل|وش أسأل|وش اسأل|ايش أسأل|إيش أسأل"
        r"|ما السؤال|أي سؤال|اي سؤال|ماذا أطلب|ماذا اطلب|ماذا يجب أن أسأل|أسئلة|اسئلة")),
    (EXPLAIN_CLAUSE, re.compile(
        r"اشرح|اشرحي|إشرح|وضّح|وضح|فسّر|فسر|بسّط|بسط"
        r"|ماذا يعني|ما معنى|وش يعني|ايش يعني|أبغى شرح|ابغى شرح|أريد شرح|اريد شرح"
        r"|بطريقة سهلة|بشكل سهل|بطريقة بسيطة")),
]


def match_arabic_intent(user_text: str) -> Optional[str]:
    """Return the fast-path key for an Arabic question, or None."""
    t = user_text or ""
    for key, pat in _AR_PATTERNS:
        if pat.search(t):
            return key
    return None


def modify_confirmation(user_text: str) -> str:
    """Short spoken confirmation that matches what the user asked to change."""
    t = (user_text or "").lower()
    if "short" in t:    return "I shortened the draft for you."
    if "long" in t or "more detail" in t: return "I expanded the draft for you."
    if "formal" in t:   return "I made the draft more formal."
    if "polite" in t:   return "I made the draft more polite."
    if "firm" in t or "strong" in t or "assertive" in t: return "I made the draft firmer."
    if "simpl" in t:    return "I simplified the draft for you."
    return "I've updated the draft for you."


# ── helpers ─────────────────────────────────────────────────────────────────

def _lc_first(s: str) -> str:
    """Lowercase the first letter unless it's an acronym (so sentences join cleanly)."""
    s = (s or "").strip()
    if not s:
        return s
    head = s.split()[0]
    if head.isupper() and len(head) > 1:   # e.g. "ABC", "PDF"
        return s
    return s[0].lower() + s[1:]


def _ensure_period(s: str) -> str:
    s = (s or "").strip()
    if s and s[-1] not in ".!?":
        s += "."
    return s


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text).strip()


def _find(report: dict, clause_id: Optional[str]) -> Optional[dict]:
    if not clause_id:
        return None
    return next((r for r in report.get("risks", []) if r.get("id") == clause_id), None)


_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _first_high_risk(report: dict) -> Optional[dict]:
    """Highest-severity risk (risks sorted Critical→High→Medium→Low)."""
    risks = report.get("risks", [])
    if not risks:
        return None
    return sorted(risks, key=lambda r: _SEVERITY_ORDER.get(r.get("severity", "Medium"), 9))[0]


# ── answer builders (return str, list[str], or None) ─────────────────────────

def _prefix(text: str, prefix: str, skip_if: str) -> str:
    """Prepend a natural lead-in, unless the text already starts that way
    (avoids 'This means this means…' when the report phrasing overlaps)."""
    text = (text or "").strip()
    if not text:
        return ""
    if re.match(skip_if, text, re.IGNORECASE):
        return _ensure_period(text)
    return _ensure_period(f"{prefix}{_lc_first(text)}")


def build_biggest_risk_answer(report: dict):
    r = _first_high_risk(report)
    if not r:
        return None
    title = r.get("title", "this clause")
    why = (r.get("why_it_matters") or r.get("simple_explanation") or "").strip()
    if why:
        # Strip a redundant lead-in so we don't get "because this means…".
        why = re.sub(r"^(this means that|this means|it means|this clause means)\s+", "", why, flags=re.IGNORECASE)
        tail = _prefix(why, "It matters because ", r"^(it matters|because|this matters)\b")
        return f"The biggest risk is {title}. {tail}"
    return _ensure_period(f"The biggest risk is {title}")


def build_explain_answer(report: dict, active_id: Optional[str]):
    r = _find(report, active_id)
    if not r:
        return None
    se = (r.get("simple_explanation") or "").strip()
    why = (r.get("why_it_matters") or "").strip()
    parts: list[str] = []
    if se:
        parts.append(_prefix(se, "This means ", r"^(this|it)\b"))
    if why:
        parts.append(_prefix(why, "The risk is ", r"^(the risk|this|it|while|because)\b"))
    if not parts:
        ct = (r.get("clause_text") or "").strip()
        if ct:
            parts.append(_ensure_period(f"This clause states: {ct}"))
    return parts or None


def build_should_sign_answer(report: dict):
    overall = report.get("overall_risk", "")
    rec = (report.get("final_recommendation") or "").strip()
    risks = report.get("risks", [])
    high = [r for r in risks if r.get("severity") in ("Critical", "High")]

    if (rec and "not sign" in rec.lower()) or overall in ("Critical", "High"):
        lead = "I would not sign yet."
        if high:
            reason = (
                f"The contract has {len(high)} high-risk term"
                f"{'s' if len(high) != 1 else ''} that should be clarified first."
            )
        else:
            reason = "There are high-risk terms worth clarifying first."
    elif overall == "Medium":
        lead = "It's not clearly unsafe, but review the key terms before signing."
        reason = _first_sentence(report.get("summary", "")) or \
            "A few clauses are worth questioning first."
    else:
        lead = "It looks relatively low-risk, but read the key terms first."
        reason = _first_sentence(report.get("summary", ""))

    out = _ensure_period(lead)
    if reason:
        out += " " + _ensure_period(reason)
    return out


def _negotiation_line(risk: dict) -> str:
    """One suggested thing the user could say to push back on a clause."""
    title = (risk.get("title") or "this term").strip().rstrip(".")
    return (
        f"You could say: \"I'm not comfortable with {_lc_first(title)} as written — "
        "can we adjust or remove it before I sign?\""
    )


def build_detail_explain_answer(report: dict, active_id: Optional[str]):
    """Richer, easier explanation of the active clause — up to 5 short sentences:
    what it means, why it matters, what to ask, and one negotiation suggestion.
    Deterministic (no Gemini), and intentionally worded differently from the
    short explain so it doesn't just repeat the same answer."""
    r = _find(report, active_id)
    if not r:
        return None
    se = (r.get("simple_explanation") or "").strip()
    why = (r.get("why_it_matters") or "").strip()
    q = (r.get("question_to_ask") or "").strip()
    title = (r.get("title") or "this clause").strip()

    out: list[str] = []
    if se:
        out.append(_prefix(se, "In plain terms, ", r"^(in plain|in simple|this|it)\b"))
    else:
        out.append(_ensure_period(f"This part is about {title}"))
    if why:
        out.append(_prefix(why, "It matters because ", r"^(it matters|because|this)\b"))
    if q:
        out.append(_ensure_period(f"Before you sign, ask them: {q}"))
    out.append(_negotiation_line(r))
    # Cap at 5 short sentences.
    return out[:5] or None


def build_questions_answer(report: dict, active_id: Optional[str]):
    r = _find(report, active_id)
    if r and (r.get("question_to_ask") or "").strip():
        return _ensure_period(f"A good question to ask is: {r['question_to_ask'].strip()}")
    qs = [q.strip() for q in report.get("recommended_questions", []) if q.strip()]
    if qs:
        out = ["Here are a few questions worth asking:"]
        out.extend(_ensure_period(q) for q in qs[:3])
        return out
    return None


_ORDINAL_NAMES = ["first", "second", "third", "fourth", "fifth", "sixth"]


def build_selected_clauses_answer(report: dict, selected_ids: list):
    """Deterministic, structured English answer about ONLY the selected clauses
    (no Gemini): 'The first selected clause is X… The second is Y… Together…'."""
    risks = [r for r in (_find(report, i) for i in (selected_ids or [])) if r]
    if not risks:
        return None
    if len(risks) == 1:
        return _explain_one(risks[0], lead="The selected clause is")
    out: list[str] = []
    for idx, r in enumerate(risks[:6]):
        name = _ORDINAL_NAMES[idx] if idx < len(_ORDINAL_NAMES) else f"{idx + 1}th"
        title = (r.get("title") or "this clause").strip()
        se = (r.get("simple_explanation") or "").strip()
        line = f"The {name} selected clause is {title}"
        if se:
            line += f" — {_lc_first(se)}"
        out.append(_ensure_period(line))
    out.append(
        "Together, these terms are worth clarifying and confirming in writing before you sign."
    )
    return out


def _explain_one(risk: dict, lead: str) -> list[str]:
    """Short 2–3 sentence explanation of a single risk, used by the severity and
    clause-number fast paths. `lead` introduces which risk we're explaining."""
    title = (risk.get("title") or "this clause").strip()
    se = (risk.get("simple_explanation") or "").strip()
    why = (risk.get("why_it_matters") or "").strip()
    out: list[str] = [_ensure_period(f"{lead} {title}")]
    if se:
        out.append(_prefix(se, "In plain terms, ", r"^(in plain|in simple|this|it)\b"))
    if why:
        out.append(_prefix(why, "It matters because ", r"^(it matters|because|this)\b"))
    return out


# ── Severity-specific queries (Phase 8-bugfix #4) ────────────────────────────
# "explain the low risk", "first high risk", "second low risk", "the last medium
# risk". Filter risks by severity deterministically so the agent never claims a
# severity has no items when the report actually has them.
_SEVERITY_WORDS = {
    "low": "Low", "medium": "Medium", "mid": "Medium",
    "high": "High", "critical": "Critical",
}
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "last": -1,
}
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

# A severity word adjacent to risk/clause/item/concern/issue/one — so a stray
# "high" in normal prose ("the rent is high") doesn't trigger this path.
_SEV_QUERY_RE = re.compile(
    r"\b(low|medium|mid|high|critical)\s+(risk|clause|item|concern|issue|one)s?\b"
    r"|\b(risk|clause|item|concern|issue)s?\s+(?:that (?:are|is)\s+)?(low|medium|mid|high|critical)\b",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)\b",
    re.IGNORECASE,
)


def severity_query(user_text: str):
    """Return (severity_label, ordinal) for a severity-specific query, else None.
    ordinal: 1-based index, -1 for 'last', or None for 'all of that severity'."""
    t = user_text or ""
    if not _SEV_QUERY_RE.search(t):
        return None
    m = re.search(r"\b(low|medium|mid|high|critical)\b", t, re.IGNORECASE)
    if not m:
        return None
    sev = _SEVERITY_WORDS[m.group(1).lower()]
    om = _ORDINAL_RE.search(t)
    ordinal = _ORDINAL_WORDS[om.group(1).lower()] if om else None
    return (sev, ordinal)


def _ordinal_label(idx_1based: int) -> str:
    names = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
             6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
    return names.get(idx_1based, f"{idx_1based}th")


def build_severity_answer(report: dict, user_text: str):
    """Answer a severity-specific query directly from the report."""
    sq = severity_query(user_text)
    if not sq:
        return None
    sev, ordinal = sq
    matched = [
        r for r in report.get("risks", [])
        if (r.get("severity") or "").lower() == sev.lower()
    ]
    sev_l = sev.lower()
    if not matched:
        return _ensure_period(
            f"Good news — there are no {sev_l}-risk items in this contract"
        )

    # Specific ordinal requested ("first high risk", "last low risk").
    if ordinal is not None:
        idx = len(matched) - 1 if ordinal == -1 else ordinal - 1
        if 0 <= idx < len(matched):
            pos = "last" if ordinal == -1 else _ordinal_label(idx + 1)
            return _explain_one(matched[idx], lead=f"The {pos} {sev_l}-risk item is")
        return _ensure_period(
            f"There {'is' if len(matched) == 1 else 'are'} only {len(matched)} "
            f"{sev_l}-risk item{'s' if len(matched) != 1 else ''} in this contract"
        )

    # No ordinal — one match: explain it; several: summarize and ask which.
    if len(matched) == 1:
        return _explain_one(matched[0], lead=f"The {sev_l}-risk item is")

    titles = [(m.get("title") or "this clause").strip() for m in matched]
    if len(matched) == 2:
        return _ensure_period(
            f"There are {len(matched)} {sev_l}-risk items. "
            f"The first is {titles[0]}, and the second is {titles[1]}. "
            "Which one should I explain?"
        )
    listed = ", ".join(titles[:-1]) + f", and {titles[-1]}"
    return (
        f"There are {len(matched)} {sev_l}-risk items: {listed}. "
        "Which one would you like me to explain?"
    )


# ── Clause / risk number references (Phase 8-bugfix #5) ──────────────────────
# "explain clause 6", "risk number 6", "the sixth risk", "number six" → risk_006.
_CLAUSE_NUM_RE = re.compile(
    r"\b(?:risk|clause|item|point|number|no\.?|#)\s*(?:number\s*|no\.?\s*)?(\d{1,2})\b",
    re.IGNORECASE,
)
_NUM_WORD_RE = re.compile(
    r"\b(?:risk|clause|item|point|number|no\.?)\s+(?:number\s+)?"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
# Plain ordinal + risk/clause WITHOUT a severity word ("the sixth risk").
_ORDINAL_RISK_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)\s+"
    r"(?:risk|clause|item|point|one)\b",
    re.IGNORECASE,
)


def parse_clause_number(user_text: str) -> Optional[int]:
    """Return a 1-based clause/risk number the user referenced (-1 = 'last'),
    or None. Skips severity-specific queries (handled by severity_query)."""
    t = user_text or ""
    if severity_query(t):  # "second low risk" is a severity query, not clause N
        return None
    m = _CLAUSE_NUM_RE.search(t)
    if m:
        return int(m.group(1))
    m = _NUM_WORD_RE.search(t)
    if m:
        return _NUM_WORDS.get(m.group(1).lower())
    m = _ORDINAL_RISK_RE.search(t)
    if m:
        return _ORDINAL_WORDS.get(m.group(1).lower())
    return None


def resolve_clause_by_number(report: dict, n: Optional[int]) -> Optional[dict]:
    """Map a 1-based number to a risk dict. -1 → last. Prefers the literal id
    risk_00N (PM: 'clause 6' → risk_006), then falls back to list position."""
    if n is None:
        return None
    risks = report.get("risks", [])
    if not risks:
        return None
    if n == -1:
        return risks[-1]
    rid = f"risk_{n:03d}"
    found = next((r for r in risks if r.get("id") == rid), None)
    if found:
        return found
    if 1 <= n <= len(risks):
        return risks[n - 1]
    return None


def build_clause_number_answer(report: dict, user_text: str):
    """Explain the risk referenced by number, or say it could not be found."""
    n = parse_clause_number(user_text)
    if n is None:
        return None
    risk = resolve_clause_by_number(report, n)
    if not risk:
        ref = "the last risk" if n == -1 else f"risk {n}"
        return _ensure_period(
            f"I could not find {ref} in the report. "
            "Please select the clause from the dashboard"
        )
    label = "the last risk" if n == -1 else f"risk {n}"
    return _explain_one(risk, lead=f"Looking at {label},")
