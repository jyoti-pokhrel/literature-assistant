from __future__ import annotations

import base64
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from xml.sax.saxutils import escape

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

logger = logging.getLogger(__name__)


def _decode_b64_image(b64: Optional[str]) -> Optional[bytes]:
    if not b64 or not isinstance(b64, str):
        return None
    try:
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
    except Exception as exc:
        logger.warning("Failed to decode b64 image: %s", exc)
        return None


def generate_pdf_report(
    topic: str,
    papers_analyzed: int,
    pattern,
    gaps: list,
    visualizations,
    report_id: str,
    clusters: list | None = None,
    papers: list | None = None,
) -> bytes:

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Image,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
        )
        styles = getSampleStyleSheet()

        # Styles
        h1_style = ParagraphStyle(
            "H1",
            parent=styles["Heading1"],
            textColor=colors.HexColor("#070707"),
            fontSize=20,
            spaceAfter=10,
            keepWithNext=True,
        )
        h2_style = ParagraphStyle(
            "H2",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#070707"),
            fontSize=14,
            spaceBefore=15,
            spaceAfter=6,
            keepWithNext=True,
        )
        h3_style = ParagraphStyle(
            "H3",
            parent=styles["Heading3"],
            fontSize=12,
            textColor=colors.HexColor("#4f46e5"),
            spaceBefore=10,
            keepWithNext=True,
        )
        body_style = ParagraphStyle(
            "Body", parent=styles["BodyText"], fontSize=10, leading=14
        )
        label_style = ParagraphStyle(
            "Label",
            parent=styles["BodyText"],
            fontSize=9,
            textColor=colors.HexColor("#7c3aed"),
            fontName="Helvetica-Bold",
        )
        cite_style = ParagraphStyle(
            "Cite",
            parent=styles["BodyText"],
            fontSize=9,
            leftIndent=10,
            textColor=colors.HexColor("#475569"),
        )

        def wrap_p(text, bold=False, is_html=False):
            style = ParagraphStyle(
                "TC", parent=styles["Normal"], fontSize=9, leading=13
            )
            if bold:
                style.fontName = "Helvetica-Bold"
            content = str(text) if is_html else escape(str(text))
            return Paragraph(content, style)

        def format_list(items, default_msg):
            if not items:
                return escape(default_msg)
            formatted = []
            for item in items:
                text = str(item).strip()
                if text:
                    text = text[0].upper() + text[1:]
                formatted.append(f"&bull; {escape(text)}")
            return "<br/>".join(formatted)

        story = []

        # Cover
        story.append(Paragraph("Research Synthesis Report", h1_style))
        story.append(
            Paragraph(f"<b>Topic:</b> {escape(str(topic or 'N/A'))}", body_style)
        )
        story.append(Paragraph(f"<b>Report ID:</b> {report_id}", body_style))
        story.append(
            Paragraph(
                f"<b>Generated:</b> {datetime.now(NEPAL_TZ).strftime('%Y-%m-%d %H:%M NPT')}",
                body_style,
            )
        )
        story.append(
            Paragraph(f"<b>Papers Analyzed:</b> {papers_analyzed}", body_style)
        )
        story.append(
            Paragraph(f"<b>Research Gaps Identified:</b> {len(gaps)}", body_style)
        )
        story.append(Spacer(1, 1.0 * cm))

        # Executive Summary
        story.append(Paragraph("Executive Summary", h2_style))
        if gaps:
            top = gaps[0]
            summary_text = (
                f"This synthesis analyzed <b>{papers_analyzed}</b> research papers on <b>{escape(topic)}</b>, "
                f"identifying <b>{len(gaps)}</b> research gap{'s' if len(gaps) != 1 else ''} across "
                f"<b>{len(clusters or [])}</b> semantic cluster{'s' if len(clusters or []) != 1 else ''}. "
                f"The highest-confidence gap (<b>{top.confidence_score:.2f}</b>) is: "
                f"<i>{escape(str(top.gap_title))}</i>."
            )
            story.append(Paragraph(summary_text, body_style))
        else:
            story.append(
                Paragraph(
                    f"Analysis of {papers_analyzed} papers on '{escape(topic)}' did not yield clearly defined research gaps. "
                    "Consider expanding search parameters or adjusting year/venue filters.",
                    body_style,
                )
            )
        story.append(Spacer(1, 0.6 * cm))

        # Pattern Analysis
        story.append(Paragraph("High-Level Pattern Analysis", h2_style))
        story.append(
            Paragraph(
                "This section synthesizes recurring themes, methodological trends, and dataset usage observed across the analyzed research corpus.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.3 * cm))

        top_m = (getattr(pattern, "top_methods", []) or [])[:5]
        top_met = (getattr(pattern, "top_metrics", []) or [])[:5]
        top_lim = (getattr(pattern, "top_limitations", []) or [])[:3]
        top_fw = (getattr(pattern, "top_future_work", []) or [])[:3]

        pat_data = [
            [wrap_p("Category", True), wrap_p("Synthesis of Findings", True)],
            [
                wrap_p("Methodologies"),
                wrap_p(", ".join(top_m) or "No dominant methods detected"),
            ],
            [
                wrap_p("Common Metrics"),
                wrap_p(", ".join(top_met) or "No standardized metrics found"),
            ],
            [
                wrap_p("Key Limitations"),
                wrap_p(
                    format_list(top_lim, "No recurring limitations noted"), is_html=True
                ),
            ],
            [
                wrap_p("Future Research"),
                wrap_p(
                    format_list(top_fw, "No clear future directions stated"),
                    is_html=True,
                ),
            ],
            [
                wrap_p("Baseline Stagnation"),
                wrap_p(
                    "Potential stagnation detected"
                    if getattr(pattern, "baseline_stagnation", False)
                    else "Innovation pace remains steady"
                ),
            ],
        ]
        pat_table = Table(pat_data, colWidths=[4.0 * cm, 13.0 * cm])
        pat_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f8fafc")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(pat_table)
        story.append(Spacer(1, 0.4 * cm))

        # Emerging opportunities
        opps = getattr(pattern, "emerging_opportunities", []) or []
        if opps:
            story.append(Paragraph("Emerging Opportunities", h3_style))
            for opp in opps:
                story.append(Paragraph(f"• {escape(str(opp))}", body_style))
            story.append(Spacer(1, 0.4 * cm))

        # Section removed by user request

        # Research Gaps
        story.append(Paragraph("Critical Research Gaps", h2_style))
        if not gaps:
            story.append(
                Paragraph(
                    "No significant research gaps were identified in the analyzed corpus.",
                    body_style,
                )
            )
        else:
            for i, gap in enumerate(gaps, 1):
                story.append(
                    Paragraph(
                        f"{i}. {escape(str(gap.gap_title or 'Unnamed Gap'))}", h3_style
                    )
                )
                score = float(getattr(gap, "confidence_score", 0.0) or 0.0)
                story.append(
                    Paragraph(
                        f"<b>Confidence:</b> {score:.3f} | <b>Cluster Reference:</b> #{getattr(gap, 'cluster_id', 'N/A')}",
                        label_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Impact Statement:</b> {escape(str(gap.description))}",
                        body_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Technical Constraint:</b> {escape(str(gap.what_fails))}",
                        body_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Origin of Gap:</b> {escape(str(gap.why_it_exists))}",
                        body_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Missing Component:</b> {escape(str(gap.missing_piece))}",
                        body_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Detected Pattern:</b> {escape(str(gap.pattern_detected))}",
                        body_style,
                    )
                )
                story.append(
                    Paragraph(
                        f"<b>Proposed Trajectory:</b> {escape(str(gap.proposed_direction))}",
                        body_style,
                    )
                )

                cites = getattr(gap, "citations", [])
                if cites:
                    story.append(
                        Paragraph("<b>Primary Source References:</b>", label_style)
                    )
                    for idx, c in enumerate(cites, 1):
                        title_text = escape(str(c.title))
                        if getattr(c, "url", None):
                            title_text = f'<a href="{escape(str(c.url))}" color="#4f46e5"><u>{title_text}</u></a>'
                        story.append(
                            Paragraph(
                                f"[{idx}] {title_text} ({c.year or 'N/A'})", cite_style
                            )
                        )
                story.append(Spacer(1, 0.5 * cm))

        # Recommendations
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Synthesis Recommendations", h2_style))
        if gaps:
            top_gap = gaps[0]
            rec_text = getattr(
                top_gap,
                "proposed_direction",
                "Explore identified clusters for novel research paths.",
            )
            story.append(
                Paragraph(
                    f"<b>Primary Research Trajectory:</b> {escape(str(rec_text))}",
                    body_style,
                )
            )
        else:
            story.append(
                Paragraph(
                    "Based on the current analysis, we recommend expanding the search parameters to identify more niche research clusters.",
                    body_style,
                )
            )

        # Visualizations
        story.append(Spacer(1, 0.8 * cm))
        story.append(Paragraph("Analytical Visualizations", h2_style))
        story.append(
            Paragraph(
                "The following charts provide a visual decomposition of the research landscape based on "
                "semantic embedding, cluster analysis, and metadata-driven frequency analysis.",
                body_style,
            )
        )

        # Only static b64 charts can be embedded in PDF
        chart_fields = [
            ("umap_scatter", "Semantic Cluster Mapping (UMAP)"),
            ("confidence_bars", "Gap Confidence Distribution"),
            ("year_distribution", "Temporal Publication Density"),
        ]

        found_viz = False
        for field, chart_title in chart_fields:
            b64 = (
                visualizations.get(field)
                if isinstance(visualizations, dict)
                else getattr(visualizations, field, None)
            )
            img_bytes = _decode_b64_image(b64)
            if img_bytes:
                try:
                    story.append(
                        Paragraph(
                            chart_title,
                            ParagraphStyle(
                                "ChartT",
                                parent=styles["Normal"],
                                fontSize=11,
                                fontName="Helvetica-Bold",
                                spaceBefore=15,
                                spaceAfter=8,
                            ),
                        )
                    )
                    img = Image(io.BytesIO(img_bytes), width=16 * cm, height=9 * cm)
                    img.hAlign = "CENTER"
                    story.append(img)
                    story.append(Spacer(1, 0.5 * cm))
                    found_viz = True
                except Exception:
                    continue

        if not found_viz:
            story.append(
                Paragraph(
                    "Visual analytics are currently being generated or were unavailable for this report corpus.",
                    body_style,
                )
            )

        doc.build(story)
        return buf.getvalue()

    except Exception as exc:
        logger.exception("Advanced PDF generation failed: %s", exc)
        return _minimal_pdf(topic, report_id, gaps)


def _minimal_pdf(topic: str, report_id: str, gaps: list) -> bytes:
    """Bare-bones PDF fallback when ReportLab is unavailable or fails."""
    lines = [
        "Research Synthesis Report",
        f"Topic: {topic}",
        f"Report ID: {report_id}",
        f"Generated: {datetime.now(NEPAL_TZ).isoformat()}",
        "",
        "Research Gaps:",
    ]
    for i, gap in enumerate(gaps, 1):
        lines.append(f"{i}. {gap.gap_title} (confidence: {gap.confidence_score:.3f})")
        lines.append(f"   {gap.description}")
    content = "\n".join(lines)
    text_escaped = content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream_lines = ["BT /F1 10 Tf 50 750 Td 12 TL"]
    for line in text_escaped.split("\n"):
        stream_lines.append(f"({line[:150]}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines)
    body = (
        "%PDF-1.4\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        f"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>/Parent 2 0 R>>>>endobj\n"
        f"4 0 obj<</Length {len(stream)}>>\nstream\n{stream}\nendstream\nendobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        "xref\n0 6\n"
        "trailer<</Size 6/Root 1 0 R>>\n"
        "startxref\n0\n%%EOF"
    )
    return body.encode("latin-1", errors="replace")
