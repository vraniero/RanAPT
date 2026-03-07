from pathlib import Path
from datetime import datetime
import re

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

AGENT_DISPLAY_NAMES = {
    "asset-reader": "Portfolio Overview",
    "global-financial-intelligence": "Global Market Intelligence",
    "real-estate-assessor": "Real Estate Assessment",
}

AGENT_ORDER = ["asset-reader", "global-financial-intelligence", "real-estate-assessor"]


def _parse_markdown_to_flowables(text: str, styles) -> list:
    """Line-by-line markdown → ReportLab flowables."""
    flowables = []
    normal = styles["Normal"]
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Headings
        if line.startswith("### "):
            flowables.append(Paragraph(line[4:], h3))
            i += 1
            continue
        if line.startswith("## "):
            flowables.append(Paragraph(line[3:], h2))
            i += 1
            continue
        if line.startswith("# "):
            flowables.append(Paragraph(line[2:], h1))
            i += 1
            continue

        # Bullet
        if line.startswith("- ") or line.startswith("* "):
            content = line[2:]
            content = _inline_markup(content)
            flowables.append(Paragraph(f"• {content}", styles["Normal"]))
            i += 1
            continue

        # Table row (basic)
        if line.startswith("|") and "|" in line[1:]:
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            # Filter separator rows
            rows = []
            for tl in table_lines:
                if re.match(r"^\|[\s\-|:]+\|$", tl):
                    continue
                cells = [c.strip() for c in tl.strip("|").split("|")]
                rows.append(cells)
            if rows:
                col_count = max(len(r) for r in rows)
                # Pad rows
                rows = [r + [""] * (col_count - len(r)) for r in rows]
                t = Table(rows, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]))
                flowables.append(t)
                flowables.append(Spacer(1, 0.2 * cm))
            continue

        # Horizontal rule
        if line.strip() in ("---", "===", "***"):
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            i += 1
            continue

        # Empty line
        if not line.strip():
            flowables.append(Spacer(1, 0.15 * cm))
            i += 1
            continue

        # Regular paragraph
        content = _inline_markup(line)
        flowables.append(Paragraph(content, normal))
        i += 1

    return flowables


def _inline_markup(text: str) -> str:
    """Convert **bold** and *italic* to ReportLab XML tags."""
    # Escape < > & first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def generate_report(
    snapshot_id: int,
    folder_path: str,
    results_map: dict,
    output_path: Path,
) -> None:
    """Generate PDF assessment report."""
    if not REPORTLAB_AVAILABLE:
        raise ImportError("reportlab is not installed")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontSize=28,
        textColor=colors.HexColor("#1a252f"),
        spaceAfter=12,
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontSize=14,
        textColor=colors.HexColor("#7f8c8d"),
        alignment=TA_CENTER,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#2c3e50"),
        spaceBefore=14,
        spaceAfter=8,
        borderPad=4,
    ))

    flowables = []

    # ── Cover Page ──────────────────────────────────────────────────────────────
    flowables.append(Spacer(1, 4 * cm))
    flowables.append(Paragraph("RanAPT", styles["CoverTitle"]))
    flowables.append(Paragraph("Portfolio Assessment Report", styles["CoverSubtitle"]))
    flowables.append(Spacer(1, 1 * cm))
    flowables.append(HRFlowable(width="60%", thickness=2, color=colors.HexColor("#2c3e50"), hAlign="CENTER"))
    flowables.append(Spacer(1, 1 * cm))

    generated_at = datetime.now().strftime("%B %d, %Y %H:%M")
    flowables.append(Paragraph(f"Generated: {generated_at}", styles["CoverSubtitle"]))
    flowables.append(Paragraph(f"Snapshot ID: {snapshot_id}", styles["CoverSubtitle"]))
    flowables.append(Paragraph(f"Source: {folder_path}", styles["CoverSubtitle"]))
    flowables.append(PageBreak())

    # ── Agent Sections ─────────────────────────────────────────────────────────
    for agent_name in AGENT_ORDER:
        display_name = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
        result = results_map.get(agent_name, {})

        flowables.append(Paragraph(display_name, styles["SectionTitle"]))
        flowables.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#bdc3c7")))
        flowables.append(Spacer(1, 0.3 * cm))

        status = result.get("status", "pending")

        if status == "completed":
            raw = result.get("raw_response", "")
            tokens_in = result.get("input_tokens", 0)
            tokens_out = result.get("output_tokens", 0)
            flowables.extend(_parse_markdown_to_flowables(raw, styles))
            flowables.append(Spacer(1, 0.4 * cm))
            flowables.append(Paragraph(
                f"<i>Tokens used: {tokens_in} input / {tokens_out} output</i>",
                styles["Normal"],
            ))
        elif status == "failed":
            err = result.get("error_message", "Unknown error")
            flowables.append(Paragraph(f"<b>Agent failed:</b> {err}", styles["Normal"]))
        else:
            flowables.append(Paragraph(f"<i>Status: {status}</i>", styles["Normal"]))

        flowables.append(PageBreak())

    # ── Appendix ───────────────────────────────────────────────────────────────
    flowables.append(Paragraph("Appendix", styles["SectionTitle"]))
    flowables.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#bdc3c7")))
    flowables.append(Spacer(1, 0.3 * cm))
    flowables.append(Paragraph(
        "This report was generated automatically by RanAPT using Claude AI agents. "
        "The analysis is for informational purposes only and does not constitute personalized "
        "financial advice. Investment decisions should be made in consultation with a licensed "
        "financial advisor considering your individual circumstances, risk tolerance, and "
        "investment objectives.",
        styles["Normal"],
    ))

    doc.build(flowables)
