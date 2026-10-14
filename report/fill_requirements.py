"""Build the completed CS3235 requirements document from the course template.

The template file supplies every style, font, margin and table border, so this
script clears the template body and rewrites it with project content using the
same formatting primitives the template itself uses.

    uv run python report/fill_requirements.py

Team member names, roll numbers, faculty mentor and sign-off rows are left
blank on purpose for the team to fill in by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "CS3235_Project_Requirements_Template.docx"
OUTPUT = ROOT / "CS3235_Project_Requirements_Filled.docx"
DIAGRAM = ROOT / "report" / "architecture.png"

TABLE_WIDTH = 9026  # dxa; matches the template content width (A4, 1in margins)
HEADER_FILL = "1F4E79"
BAND_FILL = "F2F6FA"
CELL_BORDER = "BFBFBF"
BODY_SZ = 19  # half-points, matches the template's table text

MAX_CELL_CHARS = 330  # keeps table cells readable; enforced at build time

W = nsdecls("w")


def xml(fragment: str):
    return parse_xml(fragment)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# body primitives
# --------------------------------------------------------------------------


def clear_body(document) -> None:
    """Remove every block from the template body, keeping the section properties."""
    body = document.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def append(document, element) -> None:
    body = document.element.body
    sect = body.find(qn("w:sectPr"))
    if sect is None:
        body.append(element)
    else:
        sect.addprevious(element)


def title(document, text: str) -> None:
    append(
        document,
        xml(
            f'<w:p {W}><w:pPr><w:pStyle w:val="Title"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        ),
    )


def subtitle_rule(document, text: str) -> None:
    append(
        document,
        xml(
            f"<w:p {W}><w:pPr>"
            f'<w:pBdr><w:bottom w:val="single" w:color="1F4E79" w:sz="8" w:space="6"/></w:pBdr>'
            f'<w:spacing w:after="240"/></w:pPr>'
            f'<w:r><w:rPr><w:color w:val="6B6B6B"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        ),
    )


def heading(document, text: str) -> None:
    append(
        document,
        xml(
            f'<w:p {W}><w:pPr><w:pStyle w:val="Heading1"/><w:keepNext/>'
            f'<w:spacing w:before="280" w:after="120"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        ),
    )


def para(document, text: str, *, lead: str | None = None, after: int = 120) -> None:
    """A body paragraph, optionally opening with a bold lead-in phrase."""
    runs = ""
    if lead:
        runs += (
            f'<w:r><w:rPr><w:b/><w:bCs/></w:rPr><w:t xml:space="preserve">{esc(lead)}</w:t></w:r>'
        )
    runs += f'<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r>'
    append(document, xml(f'<w:p {W}><w:pPr><w:spacing w:after="{after}"/></w:pPr>{runs}</w:p>'))


def caption(document, text: str) -> None:
    append(
        document,
        xml(
            f'<w:p {W}><w:pPr><w:spacing w:after="160"/></w:pPr>'
            f'<w:r><w:rPr><w:i/><w:iCs/><w:color w:val="6B6B6B"/><w:sz w:val="19"/>'
            f'<w:szCs w:val="19"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        ),
    )


def bullets(document, items: list[str], *, num_id: int = 2) -> None:
    for i, item in enumerate(items):
        after = 120 if i == len(items) - 1 else 40
        lead, _, rest = item.partition(" — ")
        if rest:
            runs = (
                f"<w:r><w:rPr><w:b/><w:bCs/></w:rPr>"
                f'<w:t xml:space="preserve">{esc(lead)} — </w:t></w:r>'
                f'<w:r><w:t xml:space="preserve">{esc(rest)}</w:t></w:r>'
            )
        else:
            runs = f'<w:r><w:t xml:space="preserve">{esc(item)}</w:t></w:r>'
        append(
            document,
            xml(
                f'<w:p {W}><w:pPr><w:pStyle w:val="ListParagraph"/>'
                f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
                f'<w:spacing w:after="{after}"/></w:pPr>{runs}</w:p>'
            ),
        )


def steps(document, items: list[str], *, start: int = 1) -> int:
    """A manually numbered list with a hanging indent (the template has no decimal list).

    Returns the next free number so a list interrupted by a code block can continue.
    """
    for i, item in enumerate(items, start=start):
        after = 120 if i == start + len(items) - 1 else 40
        append(
            document,
            xml(
                f'<w:p {W}><w:pPr><w:ind w:left="454" w:hanging="454"/>'
                f'<w:spacing w:after="{after}"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{i}.\t{esc(item)}</w:t></w:r></w:p>'
            ),
        )
    return start + len(items)


def formula(document, text: str) -> None:
    append(
        document,
        xml(
            f'<w:p {W}><w:pPr><w:spacing w:before="120" w:after="120"/>'
            f'<w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"'
            f' w:cs="Cambria Math" w:eastAsia="Cambria Math"/><w:i/><w:iCs/>'
            f'<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        ),
    )


def _cell(text: str, width: int, *, header: bool, band: bool) -> str:
    shade = HEADER_FILL if header else (BAND_FILL if band else None)
    shd = f'<w:shd w:fill="{shade}" w:color="auto" w:val="clear"/>' if shade else ""
    if header:
        rpr = (
            f'<w:rPr><w:b/><w:bCs/><w:color w:val="FFFFFF"/><w:sz w:val="{BODY_SZ}"/>'
            f'<w:szCs w:val="{BODY_SZ}"/></w:rPr>'
        )
    else:
        rpr = f'<w:rPr><w:sz w:val="{BODY_SZ}"/><w:szCs w:val="{BODY_SZ}"/></w:rPr>'

    paragraphs = ""
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        after = 0 if i == len(lines) - 1 else 40
        paragraphs += (
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="{after}"/></w:pPr>'
            f'<w:r>{rpr}<w:t xml:space="preserve">{esc(line)}</w:t></w:r></w:p>'
        )

    return (
        f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{width}"/>'
        f"<w:tcBorders>"
        f'<w:top w:val="single" w:color="{CELL_BORDER}" w:sz="4"/>'
        f'<w:left w:val="single" w:color="{CELL_BORDER}" w:sz="4"/>'
        f'<w:bottom w:val="single" w:color="{CELL_BORDER}" w:sz="4"/>'
        f'<w:right w:val="single" w:color="{CELL_BORDER}" w:sz="4"/>'
        f"</w:tcBorders>{shd}"
        f'<w:tcMar><w:top w:type="dxa" w:w="60"/><w:left w:type="dxa" w:w="100"/>'
        f'<w:bottom w:type="dxa" w:w="60"/><w:right w:type="dxa" w:w="100"/></w:tcMar>'
        f"</w:tcPr>{paragraphs}</w:tc>"
    )


def table(document, headers: list[str], rows: list[list[str]], weights: list[float]) -> None:
    """Emit a table in the template's own visual style.

    weights are relative column widths; they are normalised to the page width.
    """
    total = sum(weights)
    widths = [int(TABLE_WIDTH * w / total) for w in weights]
    widths[-1] += TABLE_WIDTH - sum(widths)

    for row in rows:
        if len(row) != len(headers):
            raise ValueError(f"row has {len(row)} cells, expected {len(headers)}: {row[:1]}")
        for value in row:
            if len(value) > MAX_CELL_CHARS:
                LONG_CELLS.append((headers[0], len(value), value[:70]))

    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    trs = (
        "<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>"
        + "".join(
            _cell(h, w, header=True, band=False) for h, w in zip(headers, widths, strict=True)
        )
        + "</w:tr>"
    )
    for index, row in enumerate(rows, start=1):
        band = index % 2 == 0
        trs += (
            "<w:tr><w:trPr><w:cantSplit/></w:trPr>"
            + "".join(
                _cell(v, w, header=False, band=band) for v, w in zip(row, widths, strict=True)
            )
            + "</w:tr>"
        )

    append(
        document,
        xml(
            f'<w:tbl {W}><w:tblPr><w:tblW w:type="dxa" w:w="{TABLE_WIDTH}"/>'
            f"<w:tblBorders>"
            f'<w:top w:val="single" w:color="auto" w:sz="4"/>'
            f'<w:left w:val="single" w:color="auto" w:sz="4"/>'
            f'<w:bottom w:val="single" w:color="auto" w:sz="4"/>'
            f'<w:right w:val="single" w:color="auto" w:sz="4"/>'
            f'<w:insideH w:val="single" w:color="auto" w:sz="4"/>'
            f'<w:insideV w:val="single" w:color="auto" w:sz="4"/>'
            f"</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{trs}</w:tbl>"
        ),
    )
    append(document, xml(f'<w:p {W}><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>'))


def picture(document, path: Path, width_inches: float) -> None:
    holder = document.add_paragraph()
    holder.alignment = 1
    holder.add_run().add_picture(str(path), width=Inches(width_inches))
    append(document, holder._p)


LONG_CELLS: list[tuple[str, int, str]] = []


# --------------------------------------------------------------------------
# document content
# --------------------------------------------------------------------------


def build() -> Path:
    document = docx.Document(str(TEMPLATE))
    clear_body(document)

    title(document, "CS3235 Course Project — Requirements Document")
    subtitle_rule(
        document,
        "AI-Based Construction Safety Inspection and Compliance  ·  v1.1  ·  14-10-2026",
    )

    section_1(document)
    section_2(document)
    section_3(document)
    section_4(document)
    section_5(document)
    section_6(document)
    section_7(document)
    section_8(document)
    section_9(document)
    section_10(document)
    section_11(document)
    section_12(document)
    section_13(document)
    section_14(document)
    section_15(document)
    section_16(document)
    section_17(document)

    document.save(str(OUTPUT))
    return OUTPUT


def section_1(d) -> None:
    heading(d, "1. Project overview")
    table(
        d,
        ["Field", "Details"],
        [
            ["Project title", "AI-Based Construction Safety Inspection and Compliance"],
            ["Team ID", ""],
            ["Team members (name, roll no., role)", ""],
            ["Faculty mentor", ""],
            [
                "Primary course module",
                "3 Multimodal (primary): Gemini vision reviews worker crops and proposes zones "
                "from keyframes. Also draws on 5 Advanced apps & benchmarking and 1 LLM "
                "foundations.",
            ],
            ["Version / date", "v1.1, 14-10-2026 (as-built revision of v1.0, 25-09-2026)"],
        ],
        [1.0, 2.1],
    )

    para(
        d,
        "Construction has the highest occupational fatality rate of any industry in India, and a "
        "large site may hold hundreds of workers watched by a handful of safety staff. CCTV review "
        "today is reactive, done after an incident. Automatic detection tools exist, but they "
        "output bare alerts such as “helmet missing in Zone 3 at 00:14” with no indication of "
        "which regulation applies or what to do about it. A supervisor cannot act on that alone: "
        "they need the governing clause, a corrective action, and a way to ask questions about the "
        "footage in plain language.",
        lead="Problem statement. ",
    )
    para(
        d,
        "Detection, tracking and rule evaluation in this project are fully deterministic — the "
        "rule engine alone decides whether rules R1–R5 fired, at what severity, and on what "
        "evidence. The LLM is added only for the three tasks a rule engine cannot perform:",
        lead="Why an LLM? ",
        after=60,
    )
    bullets(
        d,
        [
            "Resolve visual ambiguity — the classifier returns “unknown” when a worker is blocked "
            "from view or badly lit. A vision model can describe what is actually visible.",
            "Write up the law — the corrective action must cite the specific sub-clause of the "
            "BOCW Act 1996 or Central Rules 1998 and read as guidance, not as a fixed lookup "
            "string.",
            "Answer free-text questions — questions such as “which workers were near machinery "
            "without required equipment?” cannot all be built as fixed screens in advance.",
        ],
    )
    para(
        d,
        "A construction-site safety tool that helps safety officers act on video-detected hazards "
        "by using an LLM to retrieve the governing legal clause, explain unclear visual evidence, "
        "and answer questions about a processed clip.",
        lead="One-line solution summary. ",
    )


def section_2(d) -> None:
    heading(d, "2. Scope and users")
    para(d, "In scope — what the finished system will do:", after=60)
    bullets(
        d,
        [
            "An offline pipeline on the developer's machine: detect people and equipment, track "
            "identities, classify protective equipment, apply rules R1–R5, and render an annotated "
            "video beside a 2.5D plan view of the site.",
            "A published run containing incidents, evidence images, rule coverage and a web-sized "
            "video, uploaded to a cloud service at a public URL.",
            "Five LLM layers: image adjudication and scene proposals on the laptop, cited "
            "corrective-action briefings, run-scoped question answering on the Space, a "
            "fine-tuning experiment, and deterministic checks over every generated answer.",
            "A public Hugging Face Space (Gradio) that lists published runs, plays the video, "
            "shows briefings and answers questions.",
        ],
    )
    para(d, "Out of scope — deliberately not built this semester:", after=60)
    bullets(
        d,
        [
            "Real-time live-feed monitoring; the pipeline processes pre-recorded clips only.",
            "Mobile application; desktop browser at 1280 px minimum width only.",
            "BIM import or 3D reconstruction; the plan view is 2.5D and approximate.",
            "User accounts and per-user isolation; the demo Space is public and read-only, and "
            "only the developer's laptop can publish.",
            "A custom domain; the free provider subdomain is used instead.",
        ],
    )

    para(d, "Target users", after=60)
    table(
        d,
        ["User type", "What they need from the system", "How they interact"],
        [
            [
                "Site safety officer",
                "Review incidents detected in a processed clip, read a briefing citing the law "
                "that governs each one, and ask follow-up questions in plain English.",
                "Web UI at the public HTTPS URL",
            ],
            [
                "Teaching assistant / evaluator",
                "Verify the submitted project independently: process a short clip, publish it, "
                "read briefings, and ask a question.",
                "Setup guide for the local pipeline; web UI for the cloud service",
            ],
        ],
        [0.9, 2.4, 1.1],
    )

    para(d, "Example user scenario", after=60)
    steps(
        d,
        [
            "A safety officer opens the Space and picks the run for a clip processed that morning.",
            "An incident reads: “Worker 17 stayed within the machinery exclusion band for 4.3 s — "
            "high severity,” with the evidence image beside it and the note “helmet present, vest "
            "uncertain — upper body partly blocked from view.”",
            "The briefing below cites the Central Rules clause on safe separation from operating "
            "plant. Clicking the citation shows the clause text.",
            "She asks “was Worker 17 near machinery at any other point?” and gets two more time "
            "ranges with evidence links. She then asks “is this legal?” and the system refuses, "
            "pointing her to the cited clauses instead.",
        ],
    )


def section_3(d) -> None:
    heading(d, "3. Functional requirements")
    para(
        d,
        "Eight requirements, four of them Must. Priority uses MoSCoW.",
        after=100,
    )
    table(
        d,
        ["ID", "Requirement (“The system shall…”)", "Priority", "How it will be verified"],
        [
            [
                "FR-1",
                "Process a fixed-camera site video offline and produce a 1920×1080 side-by-side "
                "annotated MP4 plus a structured run bundle (incidents, evidence crops, manifest).",
                "Must",
                "Smoke test: any 60–120 s clip yields the MP4 and run_manifest.json within 5 "
                "minutes.",
            ],
            [
                "FR-2",
                "Publish a run bundle to the cloud service and make it visible in the browser, "
                "with "
                "incidents, evidence crops and video proxy intact.",
                "Must",
                "Publish 3 clips end to end; assert incident counts and media match the local "
                "bundle.",
            ],
            [
                "FR-3",
                "Show, for every confirmed incident, a corrective-action briefing in which each "
                "sentence cites a retrieved BOCW clause, expandable inline to the verbatim text.",
                "Must",
                "100 briefing sentences checked by hand; citation precision ≥ 0.90.",
            ],
            [
                "FR-4",
                "Refuse any request for a statutory compliance determination, a legal verdict, or "
                "content unrelated to the loaded run.",
                "Must",
                "35 red-team prompts across 3 categories; refusal rate = 100%.",
            ],
            [
                "FR-5",
                "Adjudicate ambiguous PPE evidence with a vision model and display the verdict "
                "separately from, and without altering, the deterministic rule verdict.",
                "Should",
                "200 held-out crops; L1 precision compared against classifier-only (Ablation A).",
            ],
            [
                "FR-6",
                "Answer a free-text question about a specific run with a grounded answer, a "
                "visible trace of the retrieval and guardrail steps taken, and cited evidence.",
                "Should",
                "25 scripted scenarios over 3 frozen runs; task-success rate ≥ 0.80.",
            ],
            [
                "FR-7",
                "Block any generated output that fails a grounding check and fall back to the "
                "deterministic template instead of showing it.",
                "Should",
                "60 corruption fixtures, at least one per check; 100% caught and logged.",
            ],
            [
                "FR-8",
                "Replace template narration with the LoRA-adapted model only if it passes the "
                "Week 10 promotion gate.",
                "Could",
                "Four-arm blind holdout of 120 examples; promotion recorded in the change log.",
            ],
        ],
        [0.34, 1.95, 0.52, 1.29],
    )


def section_4(d) -> None:
    heading(d, "4. LLM design requirements")
    para(
        d,
        "The project uses five LLM layers. They are referred to as L1–L5 throughout this document.",
        after=100,
    )
    table(
        d,
        ["Layer", "What it does", "Model"],
        [
            [
                "L1",
                "Reviews protective-equipment crops of 160 px and taller, and proposes restricted "
                "zones and open edges from keyframes (one request per video, cached).",
                "Gemini (vision)",
            ],
            [
                "L2",
                "Corrective-action briefing citing retrieved BOCW clauses.",
                "Retrieval + deterministic template",
            ],
            ["L3", "Answers free-text questions about a processed clip.", "Gemini + retrieval"],
            [
                "L4",
                "Narration experiment: a small fine-tuned model against a template.",
                "Qwen 1.5B + LoRA",
            ],
            ["L5", "Checks every generated answer before the user sees it.", "No model"],
        ],
        [0.35, 2.4, 0.9],
    )
    table(
        d,
        ["Aspect", "Your choice", "Justification"],
        [
            [
                "Base model(s)",
                "gemini-3.5-flash-lite for L1 and L3 (one config key).\nQwen2.5-1.5B-Instruct-4bit "
                "+ LoRA as the L4 student.\nQwen2.5-7B-Instruct-4bit as the L4 teacher (offline "
                "only).",
                "One multimodal model covers vision review and Q&A on a free tier that needs no "
                "payment card. Qwen is Apache-2.0 and fits in 16 GB.",
            ],
            [
                "Access method",
                "Gemini: hosted HTTPS API via Google AI Studio.\nQwen: Apple MLX on the local M1 "
                "Pro.",
                "No GPU is rented. Training stays on the laptop; the Space runs no model of its "
                "own.",
            ],
            [
                "Prompting strategy",
                "A fixed JSON schema for L1 and L4, four worked examples for L4, and a context "
                "block of incidents, rule coverage and retrieved clauses for L3.",
                "A bad response breaks the schema, so it is caught automatically before the user "
                "sees it.",
            ],
            [
                "Retrieval (RAG)",
                "Hybrid. BM25 keyword scoring plus gemini-embedding-001 (768-d) vectors stored in "
                "pgvector, merged by Reciprocal Rank Fusion (k=60) and diversified with MMR "
                "(λ=0.6) to the top 4. Corpus: 27 BOCW Central Rules clauses, one chunk each.",
                "Vector search matches “protective headgear” to “safety helmet”; keyword search "
                "handles exact rule numbers. Each covers the other’s blind spot.",
            ],
            [
                "Fine-tuning",
                "LoRA on Qwen2.5-1.5B-Instruct-4bit. r=8, α=16, on the query and value projections "
                "of the top 8 of 28 layers. 311,296 trainable parameters, 0.0202% of the model, "
                "asserted against MLX before training.",
                "Tests whether adapting a small model reduces unsupported claims. Result: not "
                "promoted (75% fully valid on the holdout vs 100% template), so the template "
                "serves.",
            ],
            [
                "Agents and tools",
                "No autonomous agent was built. L3 is a fixed pipeline: legal-verdict refusal, "
                "hybrid retrieval, one Gemini call, grounding check, with each step recorded in a "
                "trace shown under the answer.",
                "A single run's incidents and coverage fit in one context block, so a fixed "
                "pipeline answered the questions tried without the cost or failure modes of tool "
                "loops.",
            ],
            [
                "Protocols",
                "Not used — no MCP or A2A.",
                "L3 calls no tools, so a tool protocol has nothing to connect.",
            ],
            [
                "Multimodal input",
                "Yes. Person crops of 160 px and taller go to Gemini vision (L1), which returns "
                "helmet and vest states; 8–12 keyframes per video give zone and edge proposals.",
                "The classifier only outputs fixed labels and returns “unknown” when a worker is "
                "blocked from view. A vision model can describe what it sees.",
            ],
            [
                "Alignment and safety",
                "System prompt: answer only from the supplied context. Legal-verdict questions are "
                "refused before any model call. The L5 checks then run on every answer.",
                "The model has no database permission to change an incident, so it cannot alter a "
                "safety verdict. The guardrail makes its text safe to display.",
            ],
        ],
        [0.7, 2.0, 2.0],
    )

    para(d, "What the L5 checks do", after=60)
    para(
        d,
        "Narration (L4) output passes a deterministic validator: required JSON shape and length, "
        "no law citation, compliance verdict, rule id or severity, every number and track id "
        "present in the request, no invented machinery, equipment, harm or weather, and the "
        "action concept preserved. Any failure discards the output and the fixed template is "
        "shown. Briefings (L2) keep only sentences whose words come from the incident or the "
        "cited clause. Q&A answers (L3) are checked for trigram overlap with their context; "
        "below 8% the answer carries a visible low-evidence warning.",
    )

    para(d, "LoRA trainable-parameter calculation (L4)", after=60)
    para(
        d,
        "LoRA freezes the model and trains a small pair of matrices beside each adapted weight. "
        "For one weight of shape d × k at rank r:",
        after=0,
    )
    formula(d, "Trainable parameters = r × (d + k)")
    para(
        d,
        "d = 1536, k = 1536 (query) and 256 (value), r = 8, 16 projections across the top 8 of "
        "28 layers. Total = 311,296 trainable parameters, which is 0.0202% of the 1.54B model.",
    )

    para(d, "LLM pipeline", after=60)
    para(
        d,
        "A question or an incident goes in; the system retrieves the law passages that apply, "
        "sends them to the model together with the evidence, checks the answer against those "
        "passages, and shows either the checked answer or a fixed template. Section 10 is the "
        "diagram.",
    )


def section_5(d) -> None:
    heading(d, "5. Data requirements")
    table(
        d,
        ["Dataset / source", "Purpose", "Size", "Format", "Licence", "Link"],
        [
            [
                "MJCSD (MaJia Construction Site Dataset)",
                "YOLO11n detection fine-tune",
                "10,000 CCTV frames, 5 cameras; used 3,200 / 1,555 / 1,505",
                "JSON boxes → YOLO txt",
                "AGPL-3.0",
                "github.com/MaJia-Cons",
            ],
            [
                "BOCW Central Rules 1998",
                "L2/L3 retrieval corpus",
                "27 clauses relevant to R1–R5",
                "Text in llm/regulations.py",
                "Public domain (Indian statute)",
                "indiacode.nic.in",
            ],
            [
                "Ultralytics Construction-PPE",
                "Two-head PPE classifier training",
                "2,094 person crops (1,641 train)",
                "YOLO txt → JPEG crops",
                "AGPL-3.0",
                "docs.ultralytics.com",
            ],
            [
                "Narration corpus",
                "L4 teacher/student training and evaluation",
                "400 / 60 / 80 generated + 40 author-written holdout",
                "JSONL",
                "Derived, owned by team",
                "local",
            ],
            [
                "SARD clips",
                "Demo display only",
                "Selected clips",
                "MP4",
                "Display only; not used for training",
                "local",
            ],
        ],
        [0.9, 0.85, 0.85, 0.5, 0.8, 1.3],
    )
    bullets(
        d,
        [
            "Preprocessing — each of the 27 clauses is one retrieval chunk with its rule number, "
            "so a citation names the exact clause. MJCSD labels map to five detector classes "
            "through config/class_map.yaml; unknown labels are rejected, not guessed.",
            "Train / test separation — MJCSD is split by camera and day (seed 42017), so "
            "consecutive frames never straddle splits; cameras are not held out. Narration "
            "splits are frozen by seed before generation, with zero subject, condition, action "
            "or source overlap between splits.",
            "Personal or sensitive data — no accounts exist, so no names or emails are stored. "
            "The database holds incident records, briefings and Q&A history; Storage holds the "
            "twin video, HTML report, evidence crops and reviewed PPE crops. Crops and "
            "keyframes sent to the free Gemini tier may be used by Google to improve its "
            "products.",
        ],
    )


def section_6(d) -> None:
    heading(d, "6. Non-functional requirements")
    table(
        d,
        ["ID", "Category", "Requirement", "Target"],
        [
            [
                "NFR-1",
                "Latency",
                "Question submitted to answer shown on the Space.",
                "≤ 8 s at p90 for a single Gemini call (answers are not streamed).",
            ],
            [
                "NFR-2",
                "Cost",
                "Total cloud spend for the project.",
                "₹0. No payment method attached to any account; free tiers only.",
            ],
            [
                "NFR-3",
                "Hardware",
                "Hardware needed to run the pipeline, train the adapter, and serve the app.",
                "Apple M1 Pro 16 GB with Metal for local work; server CPU only, no GPU rented.",
            ],
            [
                "NFR-4",
                "Reliability",
                "Behaviour when the model API is unavailable or rate-limited.",
                "Retry on HTTP 429, fail fast on an exhausted daily quota, then deterministic "
                "answers quoting the retrieved clauses. PPE verdicts are cached per crop hash and "
                "scene proposals per video.",
            ],
            [
                "NFR-5",
                "Hallucination control",
                "Generated answers with little n-gram support in the evidence.",
                "Every Q&A answer below 8% trigram overlap is flagged in the UI; narration "
                "unsupported-claim rate ≤ 2% for promotion.",
            ],
            [
                "NFR-6",
                "Safety",
                "Refusal of legal-verdict, compliance-finding and out-of-run prompts.",
                "100% refusal on the 35-prompt red-team set, maintained across releases.",
            ],
            [
                "NFR-7",
                "Privacy",
                "What user data is logged or sent to third parties.",
                "No accounts or emails stored; crops, keyframes and prompts go to Gemini; no "
                "tracing service is used. Media stays in a private bucket behind 1-hour signed "
                "links. No secrets in submitted files.",
            ],
            [
                "NFR-8",
                "Usability",
                "Time for an untrained user to open a run, read a briefing and ask a question.",
                "< 3 minutes, measured with at least 5 users in Week 11.",
            ],
        ],
        [0.42, 0.75, 1.58, 1.83],
    )


def section_7(d) -> None:
    heading(d, "7. Evaluation plan and success metrics")
    table(
        d,
        ["Metric", "What it measures", "Method", "Baseline", "Target", "Req."],
        [
            [
                "Detection mAP@50",
                "Detector quality on unseen camera-days.",
                "MJCSD test split, 1,505 frames; person and merged machinery AP50.",
                "Pretrained COCO YOLO11n",
                "Beats pretrained. Measured: person 0.671 → 0.871, machinery 0.129 → 0.867",
                "FR-1",
            ],
            [
                "Publish integrity",
                "Does the published run match the local bundle?",
                "3 clips published end to end; compare counts and media.",
                "—",
                "100% match",
                "FR-2",
            ],
            [
                "Recall@10 / nDCG@10",
                "Does retrieval surface the governing clause?",
                "120 hand-authored scenario-to-clause pairs, automated.",
                "Dense-only",
                "≥ 0.85 / ≥ 0.70",
                "FR-3",
            ],
            [
                "Citation precision",
                "Does each cited clause actually support its sentence?",
                "100 sentences by hand, 200 by LLM judge with κ reported.",
                "No retrieval",
                "≥ 0.90, κ ≥ 0.60",
                "FR-3",
            ],
            [
                "L1 adjudication precision",
                "Does vision adjudication beat the classifier on ambiguous crops?",
                "200 held-out crops, with and without L1.",
                "Classifier only",
                "Higher than baseline, else L1 is dropped",
                "FR-5",
            ],
            [
                "Refusal rate",
                "Are legal verdicts and out-of-run questions refused?",
                "35 red-team prompts across 3 categories.",
                "No system prompt",
                "100% refusal",
                "FR-4, NFR-6",
            ],
            [
                "Q&A task success",
                "Does the run-scoped Q&A answer the question from the run's evidence?",
                "25 scripted scenarios over 3 frozen runs.",
                "Deterministic answers",
                "≥ 0.80",
                "FR-6",
            ],
            [
                "Guardrail catch rate",
                "Does the guardrail stop corrupted output reaching the UI?",
                "Unit-test corruption fixtures: schema, citation, verdict, numbers, track ids.",
                "Guardrail disabled",
                "100% caught",
                "FR-7",
            ],
            [
                "Narration quality",
                "Does LoRA cut unsupported claims against the base model?",
                "Five arms on 80 generated test and 40 author-written holdout examples.",
                "Template",
                "Schema 100%, unsupported ≤ 2%. Measured: 100% / 17.5%, not promoted",
                "FR-8",
            ],
            [
                "User rating",
                "Perceived usefulness to a first-time user.",
                "5+ users rate the task flow, 1–5 scale.",
                "—",
                "≥ 4.0 average",
                "NFR-8",
            ],
        ],
        [0.95, 1.2, 1.25, 0.8, 0.9, 0.5],
    )
    bullets(
        d,
        [
            "Test sets — 120 clause-retrieval pairs, 200 held-out equipment crops, 25 Q&A "
            "scenarios and 35 red-team prompts are planned, team-authored. Measured so far: "
            "detector (MJCSD test), PPE classifier (190/198 test crops, macro-F1 0.93) and "
            "narration (120 examples); results in evaluation/results/.",
            "Standard benchmarks — none exists for this domain, so retrieval follows the BEIR "
            "method, narration uses blind human rating, and detection uses the dataset’s own test "
            "split.",
            "Ablations — image adjudication on versus off; vector search versus keyword search "
            "versus both; and template versus base versus fine-tuned model. Any layer that does "
            "not beat its baseline is dropped.",
        ],
    )


def section_8(d) -> None:
    heading(d, "8. Frontend — UI/UX specifications")
    table(
        d,
        ["Item", "Your specification"],
        [
            [
                "Framework",
                "Public review UI: Gradio Blocks on the Hugging Face Space. Local review UI: "
                "plain HTML and JavaScript served by a Python standard-library HTTP server on "
                "127.0.0.1:8765, with drag-and-drop processing and a Publish button.",
            ],
            [
                "Styling",
                "Gradio's default theme on the Space; plain CSS with a warm neutral palette in "
                "the local UI. No external component library.",
            ],
            ["Target devices", "Desktop browser, minimum viewport width 1280 px."],
            [
                "Response display",
                "The answer appears as one Markdown block once Gemini returns, with any "
                "low-evidence warning and the step trace below it. Cited clause and incident ids "
                "are stored with the answer in chat_messages.",
            ],
            [
                "Error and empty states",
                "No runs: an explicit empty message. Gemini unavailable or out of quota: a "
                "deterministic answer quoting the retrieved clauses, with the failure in its "
                "trace. Missing media: the video panel says so.",
            ],
            [
                "Accessibility",
                "Gradio's built-in keyboard support and labelled controls; incident status is "
                "written as text, not carried by colour alone.",
            ],
            ["Wireframes", "Not produced; the Gradio layout replaced the planned custom UI."],
        ],
        [0.8, 3.0],
    )

    para(d, "Screens", after=60)
    table(
        d,
        ["Screen", "Purpose", "Key UI elements", "Req."],
        [
            [
                "Local review (laptop)",
                "Process a clip and publish it.",
                "Drop zone, twin video, incident list with evidence crops, HTML report link, "
                "Publish to Space button.",
                "FR-1, FR-2",
            ],
            [
                "Runs (Space)",
                "Pick a published run.",
                "Refresh button, run dropdown, run list with clip name, status and date.",
                "FR-2",
            ],
            [
                "Run detail (Space)",
                "Review the run and its briefings.",
                "Signed-URL video player, run summary with rule coverage, incident cards with "
                "evidence crops, reviewed-crop grid (classifier vs Gemini), cited briefings.",
                "FR-1, FR-3",
            ],
            [
                "Ask (Space)",
                "Query the loaded run in plain English.",
                "Question box, answer with step trace and low-evidence warning, refusal text for "
                "legal-verdict questions.",
                "FR-6, FR-4",
            ],
        ],
        [0.6, 1.2, 2.2, 0.6],
    )

    para(d, "User flow", after=60)
    steps(
        d,
        [
            "Open the public Space URL and pick a run from the dropdown.",
            "The run opens with the twin video, its rule coverage and the grounded briefings.",
            "Each briefing sentence names the BOCW clause it rests on.",
            "The Ask box takes a question in plain English and returns the answer with the steps "
            "it took. Legal-verdict questions are refused.",
        ],
    )
    caption(
        d,
        "The disclaimer “Heuristic triage from video. Not legal advice.” is visible on "
        "every screen.",
    )


def section_9(d) -> None:
    heading(d, "9. Backend specifications")
    table(
        d,
        ["Item", "Your specification", "Version"],
        [
            ["Language", "Python", "3.11.9"],
            [
                "Web framework",
                "Gradio Blocks on the Space. The local review app uses the Python standard-library "
                "ThreadingHTTPServer, bound to 127.0.0.1 only.",
                "Gradio (Space SDK)",
            ],
            [
                "LLM orchestration",
                "None. Retrieval, prompting and checks are plain Python in llm/; Supabase is "
                "called through its REST API with no chain framework.",
                "—",
            ],
            [
                "Model serving",
                "Gemini (gemini-3.5-flash-lite) and gemini-embedding-001 over the hosted REST "
                "API. Qwen runs locally under MLX for L4 only and is never deployed.",
                "mlx-lm ≥ 0.28",
            ],
            [
                "Relational DB",
                "Supabase Postgres: runs, incidents, briefings, clause_chunks, chat_messages. Row "
                "Level Security on, with public read policies for the demo; writes need the "
                "service-role key.",
                "Postgres 15",
            ],
            [
                "Vector DB",
                "pgvector on the same Postgres instance, 768-d clause vectors. Keyword scoring "
                "(BM25) runs in Python over the 27-clause corpus.",
                "pgvector",
            ],
            [
                "Cache / queue",
                "No queue: processing runs on the laptop, one job at a time. Gemini PPE verdicts "
                "and scene proposals are cached on disk by content hash.",
                "—",
            ],
            [
                "Object storage",
                "Supabase Storage, private run-media bucket, served through 1-hour signed links "
                "minted per view.",
                "—",
            ],
            [
                "Authentication",
                "None for viewers: the demo is public and read-only. Publishing needs the "
                "service-role key, which only the developer's .env and the Space secrets hold.",
                "—",
            ],
            [
                "Secrets management",
                "Local .env (gitignored) and Hugging Face Space secrets; submitted files contain "
                "key names only. No secret reaches the browser.",
                "—",
            ],
        ],
        [0.75, 2.6, 0.65],
    )

    para(d, "Interfaces", after=60)
    table(
        d,
        ["Where", "Interface", "Purpose", "Request → Response", "Auth"],
        [
            [
                "Laptop",
                "safety-twin process <clip>",
                "Run the full pipeline on a clip.",
                "video → output/<run_id>/ bundle",
                "Local",
            ],
            [
                "Laptop",
                "safety-twin publish <run_dir>",
                "Upload a run's rows and media to Supabase.",
                "bundle → rows + storage objects",
                "Service key",
            ],
            [
                "Space",
                "Gradio event handlers",
                "List runs, load one, ask a question.",
                "run id / question → Markdown + video",
                "No",
            ],
        ],
        [0.48, 1.30, 1.42, 1.42, 0.42],
    )

    para(d, "Database schema", after=60)
    para(
        d,
        "cloud/schema.sql creates five tables: runs (with the run manifest), incidents, "
        "briefings, clause_chunks (27 clauses with their vectors) and chat_messages. There are "
        "no user tables; the law corpus is shared read-only data.",
    )


def section_10(d) -> None:
    heading(d, "10. Architecture diagram")
    picture(d, DIAGRAM, 6.25)
    caption(
        d,
        "Arrows 1–5 trace one Ask request; S is the signed media link for the video. Arrows A–B "
        "are the publish path from the laptop, run once per clip.",
    )
    para(d, "Component description", after=60)
    bullets(
        d,
        [
            "Video pipeline — detection (YOLO11n fine-tuned on MJCSD), tracking, PPE, scene and "
            "geometry, rules R1–R5 and rendering run on the laptop. No GPU is rented, and only "
            "person crops and keyframes leave the machine, for Gemini review.",
            "Local review app — processes a dropped clip and publishes the finished run to "
            "Supabase directly with the service-role key.",
            "Space app — a Gradio app on Hugging Face (ZeroGPU hardware, but it runs no model). "
            "It reads runs from Postgres and calls Gemini for embeddings and answers.",
            "Grounding check — runs in the Space process, uses no model, and flags answers with "
            "little trigram overlap with their context.",
            "Supabase — Postgres holds runs, incidents, briefings and the law corpus with its "
            "vectors; Storage holds the twin video, HTML report, evidence and PPE-review crops "
            "and a media index in a private bucket.",
            "Signed URLs — the Space asks Storage for 1-hour links per view, and the browser "
            "streams the video and loads the crops from Supabase directly.",
            "Gemini — the only hosted model: PPE crop review and scene proposals from the laptop, "
            "clause embeddings and answers from the Space.",
        ],
    )


def section_11(d) -> None:
    heading(d, "11. Cloud hosting and deployment (mandatory)")
    table(
        d,
        ["Item", "Your specification"],
        [
            [
                "Cloud provider",
                "Hugging Face Spaces for the public UI, Supabase for data and media, Google AI "
                "Studio for models. All free tier.",
            ],
            [
                "Free tier / credits",
                "Free tiers only. No payment method is attached to any account.",
            ],
            [
                "Frontend hosting",
                "The Gradio app is the frontend and backend in one Space process.",
            ],
            [
                "Backend hosting",
                "Hugging Face Space, Gradio SDK, Python 3.11, ZeroGPU hardware (used only by a "
                "health-check callback). Sleeps when idle.",
            ],
            [
                "LLM hosting",
                "Gemini free tier via Google AI Studio; per-model limits are checked in AI Studio. "
                "Qwen runs only on the laptop. No GPU rented at any point.",
            ],
            [
                "Managed databases",
                "Supabase free tier: Postgres with pgvector (500 MB) and Storage (1 GB). Pauses "
                "after 7 days idle.",
            ],
            [
                "Containerisation",
                "None. The Space is built by Hugging Face from app.py and requirements.txt; the "
                "laptop uses a uv-locked environment.",
            ],
            [
                "CI/CD",
                "GitHub Actions runs ruff and pytest on pushes to main and on pull requests. The "
                "Space is deployed by a scripted folder upload with huggingface_hub.",
            ],
            [
                "Config & secrets",
                "Model ids, paths and limits in config/defaults.yaml; keys in the local .env and "
                "the Space secrets.",
            ],
            [
                "Domain and HTTPS",
                "Provider subdomain with TLS managed by Hugging Face. No custom domain, since that "
                "costs money.",
            ],
            [
                "Monitoring (LLMOps)",
                "No tracing service. Each answer is stored with its step trace in chat_messages; "
                "each run manifest records model ids and warnings, including Gemini review counts.",
            ],
            [
                "Estimated monthly cost",
                "₹0. Free tiers only; Gemini calls per run are capped by config "
                "(ppe.maximum_gemini_verifications, one scene request per video).",
            ],
            [
                "Public demo URL",
                "https://huggingface.co/spaces/Vardhan220805/safety-twin",
            ],
        ],
        [0.8, 3.0],
    )

    para(d, "Deployment steps", after=60)
    steps(
        d,
        [
            "Create the Supabase project, enable pgvector and add the private run-media bucket.",
            "Run cloud/schema.sql once in the Supabase SQL editor.",
            "Embed and upload the 27-clause corpus: uv run python -m cloud.corpus_sync.",
            "Create the Gradio Space, add the Supabase and Gemini keys as Space secrets, and "
            "upload cloud/, llm/ and shared/ with space_app.py as app.py (README, Cloud Setup).",
            "Process a clip locally, publish it, and open it on the public URL.",
        ],
    )

    para(d, "Shutdown plan", after=60)
    steps(
        d,
        [
            "Back up the database and verify the row counts.",
            "Empty and delete the media bucket, then pause the Supabase project.",
            "Pause the Hugging Face Space.",
            "Revoke the Gemini, Hugging Face and Supabase service-role keys.",
        ],
    )
    caption(
        d,
        "Each step is a dashboard action or one command, so a TA can run it unaided. No payment "
        "method is attached to any account at any point.",
    )


def section_12(d) -> None:
    heading(d, "12. Risks and mitigation")
    table(
        d,
        ["Risk", "Likelihood", "Impact", "Mitigation / fallback"],
        [
            [
                "Free-tier services sleep or pause: the Space after 48 h idle, Supabase after "
                "7 days, with a 30–60 s cold start.",
                "M",
                "M",
                "Open the Space and run one query a few minutes before the presentation; keep a "
                "local run and a backup recording ready.",
            ],
            [
                "Gemini free-tier quota exhausted during processing or the demo.",
                "M",
                "M",
                "PPE and scene results are cached per crop and per video; a run still completes "
                "on the classifier, and Q&A falls back to deterministic answers quoting the "
                "clauses.",
            ],
            [
                "Database or storage quota reached, putting Postgres into read-only mode.",
                "L",
                "M",
                "Per run only the video, report, one crop per incident and at most 48 reviewed "
                "crops are uploaded; old runs' media can be deleted while incident rows stay.",
            ],
            [
                "Detection quality on real site footage falls short of what the rules need.",
                "M",
                "H",
                "Rules R1–R5 degrade independently; a rule with insufficient evidence reports "
                "“inconclusive” with a reason code rather than guessing.",
            ],
            [
                "Geometry-dependent rules (R4, R5) cannot be evaluated on moving or sparse "
                "footage.",
                "H",
                "M",
                "Observed on the SARD clips tried: the plane fit fails its gates and R4/R5 report "
                "unsupported with a reason code; R1–R3 still run.",
            ],
        ],
        [1.25, 0.55, 0.40, 1.80],
    )
    caption(d, "Likelihood and impact are rated L (low), M (medium) or H (high).")


def section_13(d) -> None:
    heading(d, "13. Timeline and milestones")
    table(
        d,
        ["Week", "Milestone", "Deliverable", "Owner"],
        [
            [
                "1",
                "Requirements approved, cloud skeleton live",
                "This document signed off; the public cloud URL opens; Supabase is provisioned.",
                "",
            ],
            [
                "2–5",
                "CV pipeline and retrieval corpus",
                "Detection metrics on the held-out test split; BOCW corpus chunked and indexed; "
                "baseline Recall@10 measured.",
                "",
            ],
            [
                "6–8",
                "Briefings, guardrail and twin",
                "Grounded briefings with expandable citations live; L5 deployed and logging; "
                "1080p side-by-side MP4 produced from a full clip.",
                "",
            ],
            [
                "9–10",
                "Adjudication, LoRA and agent",
                "L1 verdicts on every incident card; LoRA trained and the four-arm comparison "
                "frozen; agent deployed and scored on 25 scenarios.",
                "",
            ],
            [
                "11–12",
                "Evaluation, hardening and demo",
                "All metrics frozen; usability test with 5+ users; teardown rehearsed; backup "
                "recording made; demo delivered.",
                "",
            ],
        ],
        [0.35, 1.05, 2.2, 0.5],
    )


def section_14(d) -> None:
    heading(d, "14. Final deliverables")
    bullets(
        d,
        [
            "Source code in the shared GitHub repository with a README and setup steps.",
            "A 5–7 minute demo on the deployed public URL, plus a backup recording.",
            "Final report with evaluation results mapped to FR and NFR IDs.",
            "Presentation slides.",
            "An individual contribution statement from each member.",
        ],
        num_id=3,
    )


def section_15(d) -> None:
    heading(d, "15. Open questions")
    bullets(
        d,
        [
            "Legal scope — the corpus is the BOCW Act 1996 and Central Rules 1998 only. Should "
            "state-level rules or IS standards be added, or is the central statute sufficient for "
            "a one-semester project? Needs mentor guidance in Week 1.",
            "Source footage — whether real site CCTV can be obtained through the department, or "
            "the evaluation runs entirely on public datasets. This affects how convincing the "
            "demo is. Needs mentor guidance by Week 2.",
            "Evaluation credibility — the test sets are written by the team. Should a domain "
            "expert review the clause-retrieval pairs, or is team labelling acceptable given the "
            "course scope? Needs mentor guidance by Week 4.",
            "Breadth versus depth — the fine-tuning experiment (L4) is the least essential layer. "
            "If time runs short, should it be dropped in favour of deeper evaluation of the "
            "retrieval and agent layers? Team decision at the Week 8 review.",
            "Hazard priority — rules R1\u2013R5 cover protective equipment, exclusion zones and "
            "proximity. Confirmation that these are the right five for a site safety officer "
            "would be valuable before the CV work starts in Week 2.",
        ],
    )


def section_16(d) -> None:
    heading(d, "16. Change log")
    table(
        d,
        ["Date", "Version", "Change", "Reason"],
        [
            ["25-09-2026", "v1.0", "Initial submission", "CS3235 Week 1 requirement"],
            [
                "14-10-2026",
                "v1.1",
                "As-built architecture: Gradio Space (no FastAPI, sign-in or Langfuse); fixed Q&A "
                "pipeline instead of an agent; deterministic L2 briefings; MJCSD-trained YOLO11n; "
                "27-clause corpus; measured detector and narration results; evidence and "
                "PPE-review crops published and shown; primary module set to 3 Multimodal.",
                "Align the document with the delivered system",
            ],
        ],
        [0.6, 0.5, 1.6, 1.3],
    )


def section_17(d) -> None:
    heading(d, "17. Sign-off")
    table(
        d,
        ["Role", "Name", "Signature", "Date"],
        [["Team lead", "", "", ""], ["Faculty mentor", "", "", ""]],
        [1.0, 1.0, 1.0, 1.0],
    )


if __name__ == "__main__":
    path = build()
    if LONG_CELLS:
        print(f"WARNING: {len(LONG_CELLS)} table cell(s) exceed {MAX_CELL_CHARS} characters:")
        for first, length, preview in LONG_CELLS:
            print(f"  [{first}] {length} chars: {preview}…")
        sys.exit(1)
    print(f"wrote {path}")
