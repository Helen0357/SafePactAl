"""
ReportService — generates a clean, landlord-shareable PDF of the analyzed risk
report. Phase 8I (+ Phase 8I-i18n Arabic support).

In-memory only: builds the PDF into a BytesIO and returns the raw bytes. Nothing
is written to disk and no report is stored. Uses the structured risk_report that
already lives in the session (no Gemini call).

Language:
  • English (default) — always works with reportlab's built-in fonts.
  • Arabic — when an Arabic-capable TTF font is available (system font or the
    ARABIC_PDF_FONT env var) AND arabic-reshaper + python-bidi are installed, the
    Arabic text is shaped + right-aligned. If a font is NOT available, the PDF is
    still produced (with a clear note) so the feature never hard-fails.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from io import BytesIO
from typing import Any, Optional
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

PDF_FILENAME = "ProtectMe_AI_Risk_Report.pdf"
_FALLBACK = "Not specified."
_FALLBACK_AR = "غير محدّد."

_DISCLAIMER_EN = (
    "ProtectMe AI does not replace a lawyer. It helps identify unclear or risky "
    "contract terms and prepare better questions before signing."
)
_DISCLAIMER_AR = (
    "ProtectMe AI لا يغني عن المحامي. إنه يساعدك على تحديد البنود غير الواضحة أو "
    "الخطرة وإعداد أسئلة أفضل قبل التوقيع."
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "minimal": 4}
_SEV_AR = {"critical": "حرجة", "high": "عالية", "medium": "متوسطة",
           "low": "منخفضة", "minimal": "بسيطة"}

_HEADINGS = {
    "en": {
        "title": "ProtectMe AI Contract Risk Report",
        "summary": "Summary",
        "risks": "Detected Risks",
        "no_risks": "No risks were detected in this contract.",
        "contract_type": "Contract type",
        "overall_risk": "Overall risk",
        "final_recommendation": "Final recommendation",
        "num_risks": "Number of risks",
        "generated": "Generated",
        "fields": [
            ("Category", "category"),
            ("Original clause", "clause_text"),
            ("In plain terms", "simple_explanation"),
            ("Why it matters", "why_it_matters"),
            ("Question to ask", "question_to_ask"),
            ("Suggested action", "suggested_action"),
        ],
    },
    "ar": {
        "title": "تقرير مخاطر العقد من ProtectMe AI",
        "summary": "الملخّص",
        "risks": "المخاطر المكتشفة",
        "no_risks": "لم يتم اكتشاف مخاطر في هذا العقد.",
        "contract_type": "نوع العقد",
        "overall_risk": "مستوى الخطورة العام",
        "final_recommendation": "التوصية النهائية",
        "num_risks": "عدد المخاطر",
        "generated": "تاريخ الإنشاء",
        "fields": [
            ("التصنيف", "category"),
            ("نص البند الأصلي", "clause_text"),
            ("بكلمات بسيطة", "simple_explanation"),
            ("لماذا يهمّ", "why_it_matters"),
            ("السؤال المقترح", "question_to_ask"),
            ("الإجراء المقترح", "suggested_action"),
        ],
    },
}

_AR_FONT_NAME = "PMArabic"
_arabic_font_ready: Optional[bool] = None  


def _find_arabic_font() -> Optional[str]:
    """Return a path to an Arabic-capable TTF, or None. Env override first."""
    env = os.environ.get("ARABIC_PDF_FONT")
    candidates = [env] if env else []
    candidates += [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _ensure_arabic_font() -> bool:
    """Register an Arabic TTF with reportlab once. Returns True if Arabic shaping
    is possible (font + reshaper + bidi all available)."""
    global _arabic_font_ready
    if _arabic_font_ready is not None:
        return _arabic_font_ready
    try:
        import arabic_reshaper 
        from bidi.algorithm import get_display 
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_path = _find_arabic_font()
        if not font_path:
            logger.warning("[Report] No Arabic TTF font found — Arabic PDF will use the default font.")
            _arabic_font_ready = False
            return False
        pdfmetrics.registerFont(TTFont(_AR_FONT_NAME, font_path))
        logger.info("[Report] Arabic font registered: %s", font_path)
        _arabic_font_ready = True
    except Exception as exc: 
        logger.warning("[Report] Arabic shaping unavailable (%s) — using default font.", exc)
        _arabic_font_ready = False
    return _arabic_font_ready


def _shape_ar(text: str) -> str:
    """Reshape + bidi-reorder Arabic for correct visual rendering in the PDF."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception: 
        return text


def _sev_color(severity: str):
    from reportlab.lib import colors

    s = (severity or "").strip().lower()
    return {
        "critical": colors.HexColor("#B91C1C"),
        "high": colors.HexColor("#DC2626"),
        "medium": colors.HexColor("#D97706"),
        "low": colors.HexColor("#2563EB"),
        "minimal": colors.HexColor("#16A34A"),
    }.get(s, colors.HexColor("#4B5563"))


def generate_risk_report_pdf(risk_report: dict, language: str = "en") -> bytes:
    """Build the PDF in memory and return its bytes. Never raises on missing
    fields — every field falls back to 'Not specified.' / 'غير محدّد.'."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    rr = risk_report or {}
    is_ar = str(language or "").strip().lower().startswith("ar")
    ar_ok = is_ar and _ensure_arabic_font()
    H = _HEADINGS["ar"] if is_ar else _HEADINGS["en"]
    fallback = _FALLBACK_AR if is_ar else _FALLBACK
    align = TA_RIGHT if ar_ok else TA_LEFT
    font = _AR_FONT_NAME if ar_ok else "Helvetica"
    font_bold = _AR_FONT_NAME if ar_ok else "Helvetica-Bold"

    def _val(value: Any) -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        return text if text else fallback

    def _tx(value: Any) -> str:
        """Field text → escaped for Paragraph; shaped+reordered when Arabic-ready."""
        v = _val(value)
        return escape(_shape_ar(v)) if ar_ok else escape(v)

    def _h(text: str) -> str:
        """Heading/label text (already chosen per language) → escaped (+shaped)."""
        return escape(_shape_ar(text)) if ar_ok else escape(text)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="ProtectMe AI Contract Risk Report", author="ProtectMe AI",
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle("PMTitle", parent=base["Title"], fontName=font_bold, fontSize=20,
                                 textColor=colors.HexColor("#1E3A8A"), spaceAfter=2, alignment=align)
    h2 = ParagraphStyle("PMH2", parent=base["Heading2"], fontName=font_bold, fontSize=13,
                        textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4, alignment=align)
    label_style = ParagraphStyle("PMLabel", parent=base["Normal"], fontName=font_bold, fontSize=8.5,
                                 textColor=colors.HexColor("#6B7280"), leading=11, alignment=align)
    value_style = ParagraphStyle("PMValue", parent=base["Normal"], fontName=font, fontSize=9.5,
                                 textColor=colors.HexColor("#111827"), leading=13, alignment=align)
    meta_style = ParagraphStyle("PMMeta", parent=base["Normal"], fontName=font, fontSize=9.5,
                               leading=14, alignment=align)
    small = ParagraphStyle("PMSmall", parent=base["Normal"], fontName=font, fontSize=8,
                          textColor=colors.HexColor("#6B7280"), leading=11, alignment=align)
    risk_title_style = ParagraphStyle("PMRiskTitle", parent=base["Normal"], fontName=font_bold,
                                     fontSize=11, textColor=colors.white, leading=14, alignment=align)

    risks = list(rr.get("risks", []) or [])
    ranked = sorted(
        risks, key=lambda r: _SEVERITY_ORDER.get(str(r.get("severity", "")).lower(), 9)
    )

    story: list = []
    story.append(Paragraph(_h(H["title"]), title_style))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E3A8A"),
                            spaceBefore=4, spaceAfter=8))

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_rows = [
        (H["contract_type"], _tx(rr.get("contract_type"))),
        (H["overall_risk"], _tx(rr.get("overall_risk"))),
        (H["final_recommendation"], _tx(rr.get("final_recommendation"))),
        (H["num_risks"], str(len(risks))),
        (H["generated"], generated),
    ]
    meta_cells = [[Paragraph(f"<b>{_h(k)}</b>", meta_style), Paragraph(v, meta_style)]
                  for k, v in meta_rows]
    if ar_ok:
        meta_cells = [[c[1], c[0]] for c in meta_cells] 
    meta_table = Table(meta_cells, colWidths=([None, 45 * mm] if ar_ok else [45 * mm, None]))
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)

    story.append(Spacer(1, 6))
    story.append(Paragraph(_h(_DISCLAIMER_AR if is_ar else _DISCLAIMER_EN), small))
    story.append(Spacer(1, 4))

    story.append(Paragraph(_h(H["summary"]), h2))
    story.append(Paragraph(_tx(rr.get("summary")), value_style))

    story.append(Paragraph(_h(H["risks"]), h2))
    if not ranked:
        story.append(Paragraph(_h(H["no_risks"]), value_style))

    for idx, r in enumerate(ranked, start=1):
        sev_raw = _val(r.get("severity"))
        sev_disp = _SEV_AR.get(sev_raw.lower(), sev_raw) if is_ar else sev_raw
        title = _tx(r.get("title"))
        title_cell = Paragraph(f"<b>{idx}. {title}</b>", risk_title_style)
        sev_cell = Paragraph(f"<b>{_h(str(sev_disp).upper() if not is_ar else sev_disp)}</b>", risk_title_style)
        header_cells = [[sev_cell, title_cell]] if ar_ok else [[title_cell, sev_cell]]
        header = Table(header_cells, colWidths=([28 * mm, None] if ar_ok else [None, 28 * mm]))
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _sev_color(sev_raw)),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        body_rows = []
        for label, key in H["fields"]:
            lbl = Paragraph(_h(label), label_style)
            val = Paragraph(_tx(r.get(key)), value_style)
            body_rows.append([val, lbl] if ar_ok else [lbl, val])
        body = Table(body_rows, colWidths=([None, 34 * mm] if ar_ok else [34 * mm, None]))
        label_col = 1 if ar_ok else 0
        body.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E5E7EB")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D1D5DB")),
            ("BACKGROUND", (label_col, 0), (label_col, -1), colors.HexColor("#F9FAFB")),
        ]))

        story.append(Spacer(1, 6))
        story.append(header)
        story.append(body)

    if is_ar and not ar_ok:
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            escape(
                "Note: Arabic text may not render correctly because no Arabic font is "
                "installed on the server. Set ARABIC_PDF_FONT to an Arabic .ttf to fix this."
            ),
            small,
        ))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    logger.info("[Report] Generated PDF — %d risks, %d bytes (lang=%s, arabic_shaped=%s)",
                len(risks), len(pdf_bytes), language, ar_ok)
    return pdf_bytes
