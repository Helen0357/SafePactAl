"""
ReportService — generates a clean, landlord-shareable PDF of the analyzed risk
report. Phase 8I.

In-memory only: builds the PDF into a BytesIO and returns the raw bytes. Nothing
is written to disk and no report is stored. Uses the structured risk_report that
already lives in the session (no Gemini call).
"""
from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

PDF_FILENAME = "ProtectMe_AI_Risk_Report.pdf"
_FALLBACK = "Not specified."

_DISCLAIMER = (
    "ProtectMe AI does not replace a lawyer. It helps identify unclear or risky "
    "contract terms and prepare better questions before signing."
)

# Severity ordering (High first, then Medium, then Low) + display colours.
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "minimal": 4}


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


def _val(value: Any) -> str:
    """Non-empty string for a field, or the safe fallback."""
    if value is None:
        return _FALLBACK
    text = str(value).strip()
    return text if text else _FALLBACK


def _esc(value: Any) -> str:
    """Escape for reportlab Paragraph markup (so &, <, > render literally)."""
    return escape(_val(value))


def generate_risk_report_pdf(risk_report: dict, language: str = "en") -> bytes:
    """Build the PDF in memory and return its bytes. Never raises on missing
    fields — every field falls back to 'Not specified.'."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
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
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="ProtectMe AI Contract Risk Report",
        author="ProtectMe AI",
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle("PMTitle", parent=base["Title"], fontSize=20,
                                 textColor=colors.HexColor("#1E3A8A"), spaceAfter=2)
    h2 = ParagraphStyle("PMH2", parent=base["Heading2"], fontSize=13,
                        textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)
    label_style = ParagraphStyle("PMLabel", parent=base["Normal"], fontSize=8.5,
                                 textColor=colors.HexColor("#6B7280"), leading=11,
                                 spaceAfter=0, alignment=TA_LEFT)
    value_style = ParagraphStyle("PMValue", parent=base["Normal"], fontSize=9.5,
                                 textColor=colors.HexColor("#111827"), leading=13)
    meta_style = ParagraphStyle("PMMeta", parent=base["Normal"], fontSize=9.5, leading=14)
    small = ParagraphStyle("PMSmall", parent=base["Normal"], fontSize=8,
                          textColor=colors.HexColor("#6B7280"), leading=11)
    risk_title_style = ParagraphStyle("PMRiskTitle", parent=base["Normal"], fontSize=11,
                                     textColor=colors.white, leading=14)

    risks = list(rr.get("risks", []) or [])
    ranked = sorted(
        risks, key=lambda r: _SEVERITY_ORDER.get(str(r.get("severity", "")).lower(), 9)
    )

    story: list = []

    # ── Title + meta ─────────────────────────────────────────────────────────
    story.append(Paragraph("ProtectMe AI Contract Risk Report", title_style))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E3A8A"),
                            spaceBefore=4, spaceAfter=8))

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_rows = [
        ("Contract type", _esc(rr.get("contract_type"))),
        ("Overall risk", _esc(rr.get("overall_risk"))),
        ("Final recommendation", _esc(rr.get("final_recommendation"))),
        ("Number of risks", str(len(risks))),
        ("Generated", generated),
    ]
    meta_table = Table(
        [[Paragraph(f"<b>{k}</b>", meta_style), Paragraph(v, meta_style)] for k, v in meta_rows],
        colWidths=[45 * mm, None],
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)

    story.append(Spacer(1, 6))
    story.append(Paragraph(escape(_DISCLAIMER), small))
    story.append(Spacer(1, 4))

    # ── Summary ──────────────────────────────────────────────────────────────
    summary = _val(rr.get("summary"))
    story.append(Paragraph("Summary", h2))
    story.append(Paragraph(escape(summary), value_style))

    # ── Risks (High → Medium → Low) ──────────────────────────────────────────
    story.append(Paragraph("Detected Risks", h2))
    if not ranked:
        story.append(Paragraph("No risks were detected in this contract.", value_style))

    fields = [
        ("Category", "category"),
        ("Original clause", "clause_text"),
        ("In plain terms", "simple_explanation"),
        ("Why it matters", "why_it_matters"),
        ("Question to ask", "question_to_ask"),
        ("Suggested action", "suggested_action"),
    ]

    for idx, r in enumerate(ranked, start=1):
        sev = _val(r.get("severity"))
        title = _esc(r.get("title"))
        header = Table(
            [[Paragraph(f"<b>{idx}. {title}</b>", risk_title_style),
              Paragraph(f"<b>{escape(sev.upper())}</b>", risk_title_style)]],
            colWidths=[None, 28 * mm],
        )
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _sev_color(sev)),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        body_rows = [
            [Paragraph(label, label_style), Paragraph(_esc(r.get(key)), value_style)]
            for label, key in fields
        ]
        body = Table(body_rows, colWidths=[34 * mm, None])
        body.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E5E7EB")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D1D5DB")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F9FAFB")),
        ]))

        # Keep each risk block from splitting awkwardly where possible.
        story.append(Spacer(1, 6))
        story.append(header)
        story.append(body)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    logger.info("[Report] Generated PDF — %d risks, %d bytes (lang=%s)",
                len(risks), len(pdf_bytes), language)
    return pdf_bytes
