"""
Prompt for the message generation tool.
Phase 3: full implementation.
"""
from typing import List, Optional

SYSTEM_PROMPT = """\
You are a professional communications assistant helping a user write a message about
specific clauses in a contract. You are NOT a lawyer.

Write clearly, professionally, and constructively. Do not claim legal authority.
Frame requests as polite questions or concerns, not demands or legal threats.
"""

MESSAGE_PROMPT_TEMPLATE = """\
{language_directive}Write a {message_type} message in a {tone} tone, formatted as {format}.

Contract concerns to address:
{risk_summary}

Original clause text(s):
{clause_texts}

Format guidelines for {format}:
{format_guidelines}

Keep the tone {tone} throughout. Do NOT claim to be a lawyer or make legal assertions.
End with a clear, specific next step or question.

Clause references: Do NOT write placeholder brackets like "[X]", "[Clause X]", or "[Section X]".
Instead, refer to each clause by its actual wording, category, or purpose as shown in the clause texts above.
Only names, addresses, and contact details genuinely unknown from the contract may remain as placeholders (e.g. [Your Name], [Recipient Name]).{extra_section}"""


_FORMAT_GUIDELINES_EN = (
    "- Email: include Subject line, salutation, body, and sign-off.\n"
    "- WhatsApp: short, conversational, no formal headers needed."
)
_FORMAT_GUIDELINES_AR = (
    '- البريد الإلكتروني (Email): ابدأ بسطر الموضوع بصيغة "الموضوع:"، ثم التحية، '
    "فالنص الأساسي، فالخاتمة — جميعها بالعربية.\n"
    "- واتساب (WhatsApp): رسالة قصيرة بأسلوب محادثة ودّي بالعربية، دون ترويسات رسمية."
)


_ARABIC_DIRECTIVE = (
    "اكتب الرسالة بالكامل باللغة العربية الفصحى الواضحة والمهنية. يجب أن يكون كل شيء "
    'بالعربية: سطر الموضوع، والتحية، والنص الأساسي، والخاتمة. استخدم "الموضوع:" بدلاً من '
    '"Subject:". لا تكتب أي جزء من الرسالة بالإنجليزية.\n'
    "LANGUAGE REQUIREMENT: Write the ENTIRE message in Arabic (العربية) — the subject "
    "line, greeting, body, and closing must all be Arabic. Do NOT output an English "
    'subject/greeting/body. For an email the subject label must be "الموضوع:", never '
    '"Subject:".\n\n'
)


def build_message_prompt(
    risk_summaries: List[str],
    clause_texts: List[str],
    message_type: str,
    tone: str,
    format: str,
    extra_instruction: Optional[str] = None,
    language: str = "en",
) -> str:
    is_ar = str(language or "").strip().lower().startswith("ar")
    extra_section = f"\n\nAdditional instruction: {extra_instruction}" if extra_instruction else ""
    return MESSAGE_PROMPT_TEMPLATE.format(
        message_type=message_type,
        tone=tone,
        format=format,
        risk_summary="\n".join(f"• {s}" for s in risk_summaries),
        clause_texts="\n\n".join(f'"{c}"' for c in clause_texts),
        language_directive=_ARABIC_DIRECTIVE if is_ar else "",
        format_guidelines=_FORMAT_GUIDELINES_AR if is_ar else _FORMAT_GUIDELINES_EN,
        extra_section=extra_section,
    )
