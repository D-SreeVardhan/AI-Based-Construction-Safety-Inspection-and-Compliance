"""
Converts project_report.md to project_report.docx using python-docx.
Run: python3 report/build_docx.py
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

MD = Path(__file__).parent / "project_report.md"
OUT = Path(__file__).parent / "project_report.docx"

# ── Colour palette (black only) ─────────────────────────────────────────────
C_TITLE = RGBColor(0x00, 0x00, 0x00)
C_H1 = RGBColor(0x00, 0x00, 0x00)
C_H2 = RGBColor(0x00, 0x00, 0x00)
C_H3 = RGBColor(0x00, 0x00, 0x00)
C_H4 = RGBColor(0x00, 0x00, 0x00)
C_BODY = RGBColor(0x00, 0x00, 0x00)
C_CODE = RGBColor(0x00, 0x00, 0x00)
C_TBL_HDR = RGBColor(0x00, 0x00, 0x00)


def set_font(
    run,
    name: str = "Times New Roman",
    size: int = 11,
    bold: bool = False,
    italic: bool = False,
    color: RGBColor | None = None,
) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = color


def para_space(para, before: int = 0, after: int = 6) -> None:
    para.paragraph_format.space_before = Pt(before)
    para.paragraph_format.space_after = Pt(after)


def shade_cell(cell, hex_color: str) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def set_cell_border(cell) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "C8B89A")
        borders.append(border)
    tcPr.append(borders)


def add_horizontal_rule(doc: Document) -> None:
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "C8B89A")
    pBdr.append(bottom)
    pPr.append(pBdr)
    para_space(p, before=4, after=4)


def add_title_block(doc: Document) -> None:
    """Cover-style header block."""
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = t.add_run("Construction Safety 2.5D Twin")
    set_font(run, "Georgia", 22, bold=True, color=C_TITLE)
    para_space(t, before=0, after=4)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("Project Requirements & Methodology")
    set_font(run, "Georgia", 14, italic=True, color=C_H2)
    para_space(sub, before=0, after=16)


def parse_inline(para, text: str) -> None:
    """
    Render inline markdown bold (**text**) and inline code (`text`)
    inside a paragraph. Remaining text is plain.
    """
    # Split on **bold** or `code`
    tokens = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text)
    for token in tokens:
        if token.startswith("**") and token.endswith("**"):
            run = para.add_run(token[2:-2])
            run.bold = True
            run.font.name = "Times New Roman"
            run.font.color.rgb = C_BODY
        elif token.startswith("`") and token.endswith("`"):
            run = para.add_run(token[1:-1])
            run.font.name = "Courier New"
            run.font.size = Pt(9.5)
            run.font.color.rgb = C_CODE
        else:
            run = para.add_run(token)
            run.font.name = "Times New Roman"
            run.font.color.rgb = C_BODY


def add_body_para(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    parse_inline(p, text)
    p.paragraph_format.line_spacing = Pt(16)
    para_space(p, before=0, after=6)


def add_bullet(doc: Document, text: str, level: int = 0) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.25 * (level + 1))
    parse_inline(p, text)
    p.paragraph_format.line_spacing = Pt(15)
    para_space(p, before=0, after=3)


def add_numbered(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.left_indent = Inches(0.3)
    parse_inline(p, text)
    para_space(p, before=0, after=3)


def add_code_block(doc: Document, lines: list[str]) -> None:
    p = doc.add_paragraph()
    run = p.add_run("\n".join(lines))
    run.font.name = "Courier New"
    run.font.size = Pt(8.5)
    run.font.color.rgb = C_CODE
    p.paragraph_format.left_indent = Inches(0.4)
    p.paragraph_format.line_spacing = Pt(13)
    para_space(p, before=4, after=6)


def add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.style = "Table Grid"

    for r_idx, row in enumerate(rows):
        for c_idx, cell_text in enumerate(row):
            cell = table.rows[r_idx].cells[c_idx]
            set_cell_border(cell)
            if r_idx == 0:
                shade_cell(cell, "EDE0D4")
            p = cell.paragraphs[0]
            parse_inline(p, cell_text.strip())
            for run in p.runs:
                run.font.name = "Times New Roman"
                run.font.size = Pt(9.5)
                if r_idx == 0:
                    run.bold = True
                    run.font.color.rgb = C_TBL_HDR
                else:
                    run.font.color.rgb = C_BODY
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)

    doc.add_paragraph()  # spacing after table


def parse_table_row(line: str) -> list[str] | None:
    line = line.strip()
    if not line.startswith("|"):
        return None
    parts = [c.strip() for c in line.strip("|").split("|")]
    return parts


def is_separator_row(cells: list[str]) -> bool:
    return all(re.match(r"^[-:]+$", c) for c in cells if c)


# ── Main parser ──────────────────────────────────────────────────────────────


def build_docx() -> None:
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.5)

    lines = MD.read_text(encoding="utf-8").splitlines()

    # Skip the first two heading lines (we render our own title block)
    i = 0
    first_h2_done = False

    add_title_block(doc)

    # Metadata block (lines 3-7 in the MD)
    meta_lines = []
    while i < len(lines):
        line = lines[i]
        if (
            line.startswith("**Submitted")
            or line.startswith("**Student")
            or line.startswith("**Duration")
            or line.startswith("**Hardware")
            or line.startswith("**Date")
        ):
            meta_lines.append(line)
        elif line.strip() == "---" and meta_lines:
            i += 1
            break
        i += 1

    for ml in meta_lines:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        parse_inline(p, ml.strip())
        para_space(p, before=0, after=3)
        for run in p.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(10.5)

    doc.add_paragraph()

    # Now parse the rest
    table_buffer: list[list[str]] = []
    code_buffer: list[str] = []
    in_code = False

    while i < len(lines):
        line = lines[i]

        # ── code block ──
        if line.strip().startswith("```"):
            if in_code:
                add_code_block(doc, code_buffer)
                code_buffer = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_buffer.append(line)
            i += 1
            continue

        # ── flush pending table ──
        def flush_table():
            if table_buffer:
                add_table(doc, table_buffer)
                table_buffer.clear()

        # ── horizontal rule ──
        if re.match(r"^---+$", line.strip()):
            flush_table()
            add_horizontal_rule(doc)
            i += 1
            continue

        # ── table row ──
        if line.strip().startswith("|"):
            cells = parse_table_row(line)
            if cells and is_separator_row(cells):
                i += 1
                continue
            if cells:
                table_buffer.append(cells)
                i += 1
                continue

        flush_table()

        # ── headings ──
        if line.startswith("#### "):
            p = doc.add_paragraph()
            run = p.add_run(line[5:].strip())
            set_font(run, "Georgia", 11, bold=True, color=C_H4)
            para_space(p, before=10, after=3)
        elif line.startswith("### "):
            p = doc.add_paragraph()
            run = p.add_run(line[4:].strip())
            set_font(run, "Georgia", 12, bold=True, color=C_H3)
            para_space(p, before=12, after=4)
        elif line.startswith("## "):
            text = line[3:].strip()
            if not first_h2_done:
                first_h2_done = True
            p = doc.add_paragraph()
            run = p.add_run(text)
            set_font(run, "Georgia", 14, bold=True, color=C_H2)
            para_space(p, before=16, after=6)
        elif line.startswith("# "):
            # Skip — already rendered as title block
            pass

        # ── numbered list ──
        elif re.match(r"^\d+\. ", line.strip()):
            text = re.sub(r"^\d+\. ", "", line.strip())
            add_numbered(doc, text)

        # ── bullet ──
        elif line.strip().startswith("- "):
            text = line.strip()[2:]
            indent = (len(line) - len(line.lstrip())) // 2
            # Check for bold bullet key (e.g. "- **Native drift...**")
            add_bullet(doc, text, level=indent)

        # ── blank line ──
        elif line.strip() == "":
            pass  # skip blank lines; spacing comes from para_space

        # ── body paragraph ──
        else:
            if line.strip():
                add_body_para(doc, line.strip())

        i += 1

    # flush any remaining table
    if table_buffer:
        add_table(doc, table_buffer)

    doc.save(OUT)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    build_docx()
