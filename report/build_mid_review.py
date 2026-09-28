"""Build the 4-speaker mid-review PPTX and aligned speaking script.

Layout uses labelled text blocks with a thin accent rule instead of card
outlines, so vertical space is distributed as margin rather than trapped
inside oversized boxes. Block widths are declared as fractions of the
content band and rows are packed greedily, which lets a slide mix
full-width and half-width blocks where the content suits it.
"""

from __future__ import annotations

import math
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches
from pptx.util import Pt as PptPt

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "report"
OUTPUT = REPORT / "mid_review.pptx"
SCRIPT = REPORT / "mid_review_script.md"
SCRIPT_DOCX = REPORT / "mid_review_script.docx"
CV_DIAGRAM = REPORT / "cv_pipeline.png"

C_BG = PptColor(0xFA, 0xFA, 0xF8)
C_HEAD = PptColor(0x2C, 0x25, 0x20)
C_BODY = PptColor(0x3A, 0x35, 0x30)
C_SUB = PptColor(0x6B, 0x5E, 0x52)
C_LINE = PptColor(0xCC, 0xB8, 0xA8)
C_ACCENT = PptColor(0x8B, 0x5E, 0x3C)
C_GREEN = PptColor(0x2F, 0x6F, 0x4E)
C_RED = PptColor(0x9B, 0x4A, 0x2A)
C_EVEN = PptColor(0xF7, 0xF3, 0xF0)
C_WHITE = PptColor(0xFF, 0xFF, 0xFF)
FONT = "Calibri"

SW = Inches(13.33)
SH = Inches(7.5)
TOTAL = 28

CONTENT_X = 0.55
CONTENT_W = 12.25
CONTENT_TOP = 1.20
CONTENT_BOTTOM = 6.92
GUTTER = 0.50
SPANS = {"full": 1.0, "half": 0.5, "third": 1.0 / 3.0, "twothird": 2.0 / 3.0}

PAPERS = [
    {
        "slide": 8,
        "ref": "Nath et al. 2020",
        "title": "Deep learning for site safety: real-time detection of protective equipment",
        "area": "PPE detection",
        "method": [
            "YOLO-based detector trained on a crowdsourced construction image dataset",
            "Compares three strategies: detect PPE items directly, detect combined "
            "worker-plus-PPE classes, or detect the worker then classify the crop",
            "The combined-class approach reached the best mean average precision of 72.3 percent",
            "The third strategy pairs a worker detector with a separate CNN classifier per crop",
        ],
        "contribution": [
            "Demonstrates PPE compliance checking on genuine site imagery, not staged photos",
            "Shows classifying a cropped worker beats detecting small PPE items directly",
            "Publishes construction-specific labels instead of reusing generic object classes",
            "Establishes the accuracy range a student-scale PPE system can realistically hit",
        ],
        "gap": [
            "Output is a per-frame compliance label with no worker identity or duration",
            "Covers helmet and vest only, with no reasoning about occlusion or camera angle",
            "A fixed-label classifier must still pick a class when the helmet is not visible",
        ],
        "use": [
            "Validates our detect-then-classify design: YOLO finds the worker, a second head "
            "reads PPE from the crop",
            "We keep their crop-classifier idea but add an explicit unknown state for poor "
            "visibility",
            "Their reported accuracy gives us a realistic target for our own detection metric",
        ],
    },
    {
        "slide": 9,
        "ref": "Wu et al. 2019",
        "title": "Automatic detection of hardhats worn by construction personnel",
        "area": "Hardhat detection",
        "method": [
            "Single-shot detector with an attention mechanism aimed at small objects",
            "Introduces a benchmark of site images labelled by hardhat colour",
            "Detects five classes: no-hardhat plus blue, white, yellow and red hardhats",
            "Uses a lightweight backbone chosen for practical on-site deployment",
        ],
        "contribution": [
            "Confirms helmet status is readable from CCTV-resolution imagery",
            "Colour classes let a system separate roles such as visitor, worker and supervisor",
            "Shows attention on shallow layers measurably improves small-object recall",
            "Provides a reusable public benchmark for hardhat detection",
        ],
        "gap": [
            "Helmet only, so a worker missing a vest or standing in a restricted zone is invisible",
            "Per-image detection with no tracking, so one violation recounts on every frame",
            "Produces a box on a frame rather than a record of what happened",
        ],
        "use": [
            "Supports rule R1 on mandatory helmets and flags small-object recall as a real risk",
            "Shows why our scope must cover vest and zone rules, not hardhats alone",
            "Their colour classes are a candidate later extension for role-aware rules",
        ],
    },
    {
        "slide": 10,
        "ref": "Fang et al. 2018",
        "title": "Computer vision applications in construction safety assurance",
        "area": "Survey",
        "method": [
            "Reviews computer vision work across detection, tracking and behaviour analysis",
            "Groups applications by hazard: falls, PPE non-compliance, equipment proximity, "
            "unsafe acts",
            "Compares handcrafted-feature methods against early deep learning approaches",
            "Catalogues the datasets and evaluation practices in use across the field",
        ],
        "contribution": [
            "Establishes vision-based safety assurance as a legitimate, active research area",
            "Identifies that most systems stop at detection and never close the loop to action",
            "Highlights the absence of shared construction-specific benchmarks",
            "Gives a shared vocabulary for hazard types that we adopt for our rules",
        ],
        "gap": [
            "Surveyed systems emit alerts, not records a safety officer can review and act on",
            "Almost no attention to uncertainty, occlusion, or explaining a decision",
            "Little work links a detected hazard to a regulation or a required response",
        ],
        "use": [
            "This survey defines our central gap: move from a raw alert to a usable incident",
            "Its hazard taxonomy maps almost directly onto our rules R1 to R5",
            "Its note on missing explanations is what justifies our LLM briefing layer",
        ],
    },
    {
        "slide": 11,
        "ref": "Redmon and Farhadi 2018",
        "title": "YOLOv3: An Incremental Improvement",
        "area": "Object detection",
        "method": [
            "Single-stage detector predicting boxes, objectness and classes in one forward pass",
            "Darknet-53 backbone predicting at three scales to cover different object sizes",
            "Independent per-class logistic classifiers instead of a softmax over classes",
            "Trained at several input resolutions to trade speed against accuracy",
        ],
        "contribution": [
            "Made real-time detection practical on a single GPU at usable accuracy",
            "Three-scale prediction substantially improved small-object detection",
            "Became the baseline that the construction-safety papers above are built on",
            "Its architecture is still the reference point every later tracker assumes",
        ],
        "gap": [
            "A general-purpose detector with no notion of who a person is between frames",
            "No temporal reasoning, so it cannot express duration or persistence",
            "Trained on generic classes; helmets and vests are not in its vocabulary",
        ],
        "use": [
            "Justifies a single-stage YOLO detector as the first stage of our pipeline",
            "Its multi-scale design matters because workers are small in wide CCTV views",
            "Shows we must fine-tune on construction data rather than use pretrained weights",
        ],
    },
    {
        "slide": 12,
        "ref": "Bochkovskiy et al. 2020",
        "title": "YOLOv4: Optimal Speed and Accuracy of Object Detection",
        "area": "Object detection",
        "method": [
            "CSPDarknet backbone with a path-aggregation neck and spatial pyramid pooling",
            "Training additions such as mosaic augmentation and an IoU-aware box loss",
            "Explicitly optimised for one conventional GPU rather than a training cluster",
            "Ablates which training tricks improve accuracy at no inference cost",
        ],
        "contribution": [
            "Reaches 43.5 average precision at 65 frames per second on a single GPU",
            "Shows large accuracy gains come from training strategy, not just architecture",
            "Puts strong detection within reach of modest, student-scale hardware",
            "Its ablations tell us which training choices are worth our limited time",
        ],
        "gap": [
            "Still returns only boxes and class labels for the current frame",
            "No identity, no duration and no safety verdict of any kind",
            "Accuracy on partly hidden construction objects such as a tilted helmet is untested",
        ],
        "use": [
            "Confirms our hardware budget is realistic for offline processing of recorded clips",
            "Its augmentation recipe is directly reusable when we fine-tune on site footage",
            "Reinforces that detection quality is mostly a training-data problem",
        ],
    },
    {
        "slide": 13,
        "ref": "Wang et al. 2024",
        "title": "YOLOv9: Learning What You Want to Learn",
        "area": "Object detection",
        "method": [
            "Programmable gradient information addresses signal loss through deep layers",
            "GELAN architecture combines gradient-path planning with efficient aggregation",
            "Auxiliary reversible branches are used in training and dropped at inference",
            "Compared against the whole YOLO lineage under matched parameter budgets",
        ],
        "contribution": [
            "Better accuracy than earlier YOLO versions with fewer parameters and less compute",
            "Shows the information bottleneck, not model size, was limiting deep detectors",
            "Provides a current, actively maintained reference implementation",
            "Confirms the YOLO family is still improving, so the choice is not dated",
        ],
        "gap": [
            "A benchmark-driven paper with no construction or safety evaluation",
            "Says nothing about tracking, rules or incident reporting",
            "Gains are reported on a benchmark that contains no PPE classes",
        ],
        "use": [
            "Justifies choosing a recent YOLO-family model as our detection backbone",
            "Its parameter efficiency helps us stay inside a free-tier cloud demo budget",
            "We will still validate on our own site frames rather than trust benchmark numbers",
        ],
    },
    {
        "slide": 15,
        "ref": "Zhang et al. 2022",
        "title": "ByteTrack: Multi-Object Tracking by Associating Every Detection Box",
        "area": "Tracking",
        "method": [
            "Associates every detection box with tracks in two stages, including weak ones",
            "High-confidence boxes match first using Kalman motion prediction and box overlap",
            "Remaining low-confidence boxes then match unmatched tracks to recover occlusions",
            "Deliberately uses no appearance embedding, which keeps the tracker cheap",
        ],
        "contribution": [
            "Reaches 80.3 MOTA and 77.3 IDF1 on MOT17 at around 30 frames per second",
            "Shows most tracking failures come from discarding low-confidence detections",
            "Simple enough to implement, debug and explain inside a semester project",
            "Needs no extra model to train, which keeps our pipeline auditable",
        ],
        "gap": [
            "Assumes a reasonably stable camera and can still switch identities in dense crowds",
            "Without appearance features it cannot re-identify a worker who leaves and returns",
            "Tracking quality is capped by detector quality on the same frames",
        ],
        "use": [
            "Our primary tracker, giving each worker an identity that persists across the clip",
            "Turns a bare alert into worker 17 was uncovered for 4.3 seconds",
            "Its weak-box recovery is exactly what we need when workers pass behind scaffolding",
        ],
    },
    {
        "slide": 16,
        "ref": "Aharon et al. 2022",
        "title": "BoT-SORT: Robust Associations Multi-Pedestrian Tracking",
        "area": "Tracking",
        "method": [
            "Combines Kalman motion prediction with appearance re-identification embeddings",
            "Adds camera-motion compensation estimated by registering consecutive frames",
            "Improves the Kalman state using box width and height rather than aspect ratio",
            "Fuses overlap and appearance distance into a single association cost",
        ],
        "contribution": [
            "Ahead of motion-only trackers on identity metrics on the same MOT17 benchmark",
            "Camera-motion compensation directly addresses shaky or panning site cameras",
            "Shows appearance features recover identities that motion alone loses",
            "Its width-and-height state estimate is a cheap improvement we can adopt alone",
        ],
        "gap": [
            "Higher compute plus an extra re-identification model to train and maintain",
            "Appearance embeddings are weak when every worker wears an identical uniform",
            "More hyperparameters to tune, which is a real cost on a short timeline",
        ],
        "use": [
            "Our documented fallback if ByteTrack produces too many identity switches",
            "Relevant if our source footage is handheld rather than from a fixed mount",
            "Its identical-uniform weakness is a limitation we will state in evaluation",
        ],
    },
    {
        "slide": 17,
        "ref": "Wojke et al. 2017",
        "title": "Simple Online and Realtime Tracking with a Deep Association Metric",
        "area": "Tracking",
        "method": [
            "Extends SORT with a deep appearance descriptor trained for person re-identification",
            "A matching cascade prioritises recently seen tracks to reduce fragmentation",
            "Combines a motion distance with a cosine appearance distance",
            "Runs the appearance network on every detection crop in every frame",
        ],
        "contribution": [
            "Cut identity switches by roughly 45 percent compared with plain SORT",
            "Established the appearance-plus-motion template that later trackers refined",
            "Still the most widely reproduced tracking baseline, so it is a fair comparison",
            "Its matching cascade is a well-documented idea we can borrow if needed",
        ],
        "gap": [
            "Older, and outperformed by ByteTrack and BoT-SORT on crowded sequences",
            "The appearance network adds a forward pass per detection, slowing throughput",
            "Assumes detections are reliable and discards low-confidence boxes entirely",
        ],
        "use": [
            "The baseline we cite to explain why identity tracking is needed at all",
            "Its discarding of weak detections is the precise failure ByteTrack fixes",
            "Useful as a sanity comparison if our ByteTrack numbers look implausible",
        ],
    },
    {
        "slide": 18,
        "ref": "Fang et al. 2018b",
        "title": "Falls from heights: computer vision based safety harness detection",
        "area": "Construction safety",
        "method": [
            "Two-stage pipeline: a detector locates workers, a second network checks for a harness",
            "Targets workers operating at height, where fall protection is mandatory",
            "Trained on site images of scaffolding and structural steel work",
            "Reports precision and recall for harness presence, not only detection accuracy",
        ],
        "contribution": [
            "Shows vision can target the highest-consequence hazard class, falls from height",
            "Validates a detect-then-verify pattern for a specific safety attribute",
            "Demonstrates a context-dependent rule: the harness only matters when at height",
            "Reports attribute-level precision and recall, which is how we will score PPE",
        ],
        "gap": [
            "Judges each frame independently, with no duration or persistence requirement",
            "Harness straps are thin and frequently occluded, which limits reliability",
            "Does not determine elevation automatically from the scene",
        ],
        "use": [
            "Directly supports rule R5 on elevated edges and fall risk",
            "Confirms our two-stage detect-then-classify structure for PPE attributes",
            "Its context dependence is why our rules combine PPE state with zone information",
        ],
    },
    {
        "slide": 19,
        "ref": "Sanhudo et al. 2021",
        "title": "Activity classification of construction workers",
        "area": "Activity recognition",
        "method": [
            "Classifies worker activity from wearable accelerometer signals",
            "Compares several classifiers over features extracted from signal windows",
            "Focuses on labour-intensive tasks relevant to ergonomic and safety risk",
            "Uses time-windowed features rather than instantaneous readings",
        ],
        "contribution": [
            "Shows worker behaviour is machine-recognisable into meaningful categories",
            "Time-windowed classification is markedly more reliable than per-instant labels",
            "Links activity recognition to safety outcomes, not only productivity",
            "Confirms activity categories are stable enough to be worth detecting at all",
        ],
        "gap": [
            "Sensor-based, so every worker must wear and maintain a device",
            "Produces no visual evidence, so a supervisor cannot verify the classification",
            "Does not scale to a site that already has cameras but no wearables",
        ],
        "use": [
            "Reinforces our choice of time windows over per-frame labels in the rule engine",
            "Its lack of visual evidence is why our incident cards must carry an image crop",
            "Motivates deriving activity context from video rather than from extra hardware",
        ],
    },
    {
        "slide": 20,
        "ref": "Luo et al. 2018",
        "title": "Recognising diverse construction activities in site images",
        "area": "Activity recognition",
        "method": [
            "A relevance network relates detected objects to candidate activity classes",
            "Handles many activity classes in cluttered, unconstrained site photographs",
            "Uses object co-occurrence as evidence rather than whole-image features",
            "Evaluated across a wide range of real construction activity categories",
        ],
        "contribution": [
            "Demonstrates activity recognition works on genuinely messy site imagery",
            "Object-relation reasoning generalises better than whole-image classification",
            "Establishes that context, not just the worker, decides whether a scene is unsafe",
            "Shows a model can use the scene, not just the person, as safety evidence",
        ],
        "gap": [
            "Per-image classification with no tracking, so it cannot measure how long anything "
            "lasted",
            "Cannot separate a worker passing through a zone from one working inside it",
            "No mechanism to express uncertainty when the scene is ambiguous",
        ],
        "use": [
            "Its per-frame limitation is the clearest argument for our track-first design",
            "Its object-relation idea informs how we compute worker-to-zone relations",
            "Confirms that a single frame cannot support a defensible safety verdict",
        ],
    },
    {
        "slide": 22,
        "ref": "Achiam et al. 2023",
        "title": "GPT-4 Technical Report",
        "area": "Multimodal LLM",
        "method": [
            "Transformer model accepting interleaved image and text input and producing text",
            "Post-trained with reinforcement learning from human feedback for instruction "
            "following",
            "Evaluated on academic and professional exams alongside standard benchmarks",
            "Reports a dedicated safety and refusal evaluation beside the capability numbers",
        ],
        "contribution": [
            "Shows one model can describe and reason about image content in plain language",
            "Strong instruction following makes format-controlled output practical",
            "Its documented refusal behaviour is a usable building block for a safety product",
            "Sets the expectation that a visual explanation can read as genuinely useful",
        ],
        "gap": [
            "Closed weights behind an external API, so evidence crops leave our infrastructure",
            "Still invents confident detail that is not present in the image",
            "Gives no calibrated confidence, so its judgement cannot serve as a verdict",
        ],
        "use": [
            "Supports calling a vision model only to adjudicate cases our pipeline marks unknown",
            "Its hallucination risk is why the LLM never overrides a rule outcome in our design",
            "Its refusal work backs our guardrail that declines legal-verdict questions",
        ],
    },
    {
        "slide": 23,
        "ref": "Liu et al. 2023",
        "title": "Visual Instruction Tuning (LLaVA)",
        "area": "Vision-language model",
        "method": [
            "Connects a frozen vision encoder to a language model through a projection layer",
            "Trained on machine-generated multimodal instruction-following data",
            "Two stages: align the projection first, then instruction-tune end to end",
            "Evaluated on visual question answering and open-ended visual conversation",
        ],
        "contribution": [
            "Open-weight proof that visual question answering can run on self-hosted hardware",
            "Shows synthetic instruction data is enough to teach visual conversation cheaply",
            "Gives a reproducible reference architecture we could realistically deploy",
            "Removes any dependency on a paid API for the explanation layer",
        ],
        "gap": [
            "Not construction-specific and untested on low-resolution CCTV crops",
            "Weaker than closed models on fine detail such as a partly hidden strap",
            "Ungrounded by default; it answers even with no supporting visual evidence",
        ],
        "use": [
            "Our open-weight option if evidence crops cannot be sent to an external API",
            "Its grounding weakness motivates an overlap check between answer and evidence",
            "Baseline for the idea of explaining an evidence crop in plain language",
        ],
    },
    {
        "slide": 24,
        "ref": "Yang et al. 2024",
        "title": "Qwen2.5 Technical Report",
        "area": "Open-weight LLM",
        "method": [
            "Open-weight language model family spanning roughly 0.5 to 72 billion parameters",
            "Large-scale pretraining followed by a long post-training stage for instructions",
            "Small variants explicitly targeted at resource-constrained deployment",
            "Reports structured-output and instruction-adherence benchmarks, not only knowledge",
        ],
        "contribution": [
            "A 1.5 billion parameter model small enough to fine-tune with LoRA on one GPU",
            "Open weights let the narration layer run entirely inside our own deployment",
            "Reliable structured output makes template-constrained narration feasible",
            "Small enough that the whole narration layer stays inside our own deployment",
        ],
        "gap": [
            "Text-only at the size we can afford, so it cannot look at an evidence crop",
            "Small models invent detail more readily than their larger siblings",
            "Cannot replace any part of the computer vision pipeline",
        ],
        "use": [
            "Base model for our LoRA narration experiment over incident cards",
            "Receives only the structured card fields as text, never the raw image",
            "Its invention risk is why narration is template-constrained and evidence-checked",
        ],
    },
]


def new_prs() -> Presentation:
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    return prs


def blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fill_obj = slide.background.fill
    fill_obj.solid()
    fill_obj.fore_color.rgb = C_BG
    return slide


def textbox(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.text_frame.word_wrap = True
    return tb


def run(paragraph, text, size, color=C_BODY, bold=False, italic=False):
    r = paragraph.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = PptPt(size)
    r.font.color.rgb = color
    r.font.bold = bold
    r.font.italic = italic


def set_para(tf, text, size, color=C_BODY, bold=False, align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0]
    p.clear()
    p.alignment = align
    run(p, text, size, color=color, bold=bold)
    return p


def rule_line(slide, x, y, w, color=C_LINE, thickness=1.0):
    ln = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), PptPt(thickness)
    )
    ln.fill.solid()
    ln.fill.fore_color.rgb = color
    ln.line.fill.background()
    return ln


def footer(slide, n):
    num = textbox(slide, 12.10, 7.02, 0.75, 0.26)
    set_para(num.text_frame, f"{n}/{TOTAL}", 8.4, color=C_SUB, align=PP_ALIGN.RIGHT)


def title(slide, n, text, kicker=None):
    tb = textbox(slide, 0.50, 0.16, 12.30, 0.52)
    set_para(tb.text_frame, text, 23, color=C_HEAD, bold=True)
    if kicker:
        kt = textbox(slide, 0.52, 0.68, 12.20, 0.28)
        set_para(kt.text_frame, kicker, 10.4, color=C_SUB)
    rule_line(slide, 0.50, 0.99, 12.30)
    footer(slide, n)


# --- labelled text blocks -------------------------------------------------

LABEL_H = 0.42


def chars_per_line(w, size):
    """Conservative characters-per-line estimate for Calibri at `size` points."""
    return max(12, int(w * 118.0 / size))


def block_height(w, items, size):
    cpl = chars_per_line(w - 0.15, size)
    lines = sum(max(1, math.ceil(len(t) / cpl)) for t in items)
    return LABEL_H + lines * size * 0.0175 + (len(items) - 1) * 0.055


def draw_block(slide, x, y, w, label, items, accent, size):
    lb = textbox(slide, x, y, w, 0.28)
    set_para(lb.text_frame, label.upper(), 10.6, color=accent, bold=True)
    rule_line(slide, x, y + 0.29, w, color=accent, thickness=1.1)
    body = textbox(slide, x, y + LABEL_H - 0.06, w, block_height(w, items, size) - LABEL_H + 0.1)
    tf = body.text_frame
    for idx, item in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.clear()
        p.space_before = PptPt(0 if idx == 0 else 5)
        pPr = p._pPr if p._pPr is not None else p._p.get_or_add_pPr()
        pPr.set("marL", "146050")
        pPr.set("indent", "-146050")
        run(p, "\u2022   " + item, size, color=C_BODY)


def pack_rows(blocks):
    rows, current, used = [], [], 0.0
    for block in blocks:
        frac = SPANS[block[0]]
        if current and used + frac > 1.0001:
            rows.append(current)
            current, used = [], 0.0
        current.append(block)
        used += frac
    if current:
        rows.append(current)
    return rows


MIN_GAP = 0.26
MAX_GAP = 0.85


def flow(slide, blocks, size=14, top=CONTENT_TOP, bottom=CONTENT_BOTTOM, grow=2.5):
    """Lay labelled blocks out in packed rows.

    Block widths come from the span fractions; leftover vertical space is first
    spent growing the type up to `grow` points, then split between the row gap
    and the top margin. Nothing is padded out to a fixed box size.
    """
    rows = pack_rows(blocks)
    geometry = []
    for row in rows:
        usable = CONTENT_W - GUTTER * (len(row) - 1)
        x, placed = CONTENT_X, []
        for block in row:
            w = SPANS[block[0]] * usable
            placed.append((x, w, block))
            x += w + GUTTER
        geometry.append(placed)

    gaps = max(1, len(rows) - 1)

    def measure(pt):
        heights = [max(block_height(w, b[2], pt) for _, w, b in row) for row in geometry]
        return heights, (bottom - top) - sum(heights) - MIN_GAP * gaps

    ceiling = min(17.0, size + grow)
    heights, slack = measure(size)
    while size + 0.5 <= ceiling:
        trial_h, trial_slack = measure(size + 0.5)
        # keep a full line of headroom so a mis-estimated wrap cannot overflow
        if trial_slack < 0.80:
            break
        size, heights, slack = size + 0.5, trial_h, trial_slack

    gap = min(MAX_GAP, MIN_GAP + slack / (gaps + 1))
    y = top + max(0.0, (bottom - top) - sum(heights) - gap * gaps) * 0.32
    for row, height in zip(geometry, heights, strict=True):
        for x, w, block in row:
            _, label, items, accent = block
            draw_block(slide, x, y, w, label, items, accent, size)
        y += height + gap


def table(slide, x, y, headers, rows, widths, font=10.5, row_h=0.42, head_font=None):
    tbl = slide.shapes.add_table(
        len(rows) + 1,
        len(headers),
        Inches(x),
        Inches(y),
        Inches(sum(widths)),
        Inches(row_h * (len(rows) + 1)),
    ).table
    for idx, width in enumerate(widths):
        tbl.columns[idx].width = Inches(width)
    for idx, header in enumerate(headers):
        cell = tbl.cell(0, idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = C_HEAD
        cell.margin_left = Inches(0.10)
        cell.margin_right = Inches(0.08)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        set_para(cell.text_frame, header, head_font or font, color=C_WHITE, bold=True)
    for row_idx, row in enumerate(rows, start=1):
        fill = C_EVEN if row_idx % 2 == 0 else C_BG
        for col_idx, value in enumerate(row):
            cell = tbl.cell(row_idx, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill
            cell.margin_left = Inches(0.10)
            cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.05)
            cell.margin_bottom = Inches(0.05)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            set_para(cell.text_frame, value, font, color=C_BODY)
    return tbl


# --- slides ---------------------------------------------------------------


def title_slide(prs):
    slide = blank(prs)
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.22), Inches(7.5)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = C_ACCENT
    bar.line.fill.background()

    tb = textbox(slide, 0.62, 0.74, 11.9, 1.22)
    set_para(
        tb.text_frame,
        "AI-Based Construction Safety Inspection and Compliance",
        30,
        C_HEAD,
        True,
    )
    sub = textbox(slide, 0.65, 2.02, 11.8, 0.34)
    set_para(
        sub.text_frame,
        "Mid-review video presentation  |  Computer-vision focused",
        14.5,
        C_SUB,
    )
    rule_line(slide, 0.65, 2.52, 12.0, color=C_ACCENT, thickness=1.2)
    lead = textbox(slide, 0.65, 2.70, 11.9, 0.90)
    tf = lead.text_frame
    p = tf.paragraphs[0]
    p.clear()
    run(
        p,
        "Computer vision turns construction CCTV into structured, reviewable safety "
        "incidents. The language model explains those incidents afterwards; it never "
        "decides whether a violation occurred.",
        15,
        color=C_BODY,
    )
    rows = [
        ("Nithin H", "1RVU23CSE314", "Problem statement and CV pipeline", "1 - 7"),
        ("Pavan Kumar K N", "1RVU23CSE331", "Literature: PPE and detection", "8 - 14"),
        ("Pranav Nayak", "1RVU23CSE344", "Literature: tracking and activity", "15 - 21"),
        ("Desu Sree Vardhan", "1RUA24CSE7004", "Multimodal, gaps and evaluation", "22 - 28"),
    ]
    table(
        slide,
        0.65,
        3.95,
        ["Member", "USN", "Section presented", "Slides"],
        rows,
        [2.85, 2.25, 5.35, 1.45],
        font=11,
        row_h=0.50,
    )
    footer(slide, 1)


def map_slide(prs):
    slide = blank(prs)
    title(
        slide,
        2,
        "How the presentation is organised",
        "One connected argument split across four speakers, roughly five minutes each.",
    )
    rows = [
        (
            "1",
            "Why computer vision first",
            "Motivation, precise problem statement, the CV pipeline, and the incident "
            "record it produces",
            "7",
        ),
        (
            "2",
            "PPE and detection literature",
            "Six papers on construction PPE detection and the YOLO detector family, "
            "then what detection alone cannot do",
            "7",
        ),
        (
            "3",
            "Tracking and activity literature",
            "Six papers on multi-object tracking, harness detection and construction "
            "activity recognition",
            "7",
        ),
        (
            "4",
            "Multimodal models and evaluation",
            "Three papers on vision-language models, the research gaps, our evaluation "
            "plan and scope",
            "7",
        ),
    ]
    table(
        slide,
        CONTENT_X,
        1.42,
        ["Speaker", "Section", "What it covers", "Slides"],
        rows,
        [1.15, 2.95, 7.00, 1.15],
        font=12,
        row_h=0.90,
    )
    note = textbox(slide, CONTENT_X, 6.12, CONTENT_W, 0.45)
    set_para(
        note.text_frame,
        "Fifteen papers are covered individually. Speakers 2 and 3 close with a "
        "synthesis slide so the survey builds towards a single stated gap.",
        12,
        color=C_SUB,
    )


def motivation_slide(prs):
    slide = blank(prs)
    title(
        slide,
        3,
        "CCTV is already everywhere, but safety review is still reactive",
        "The footage exists. What is missing is anything that turns it into a decision.",
    )
    flow(
        slide,
        [
            (
                "full",
                "The situation on site",
                [
                    "A large site has hundreds of workers and moving plant, supervised by "
                    "a handful of safety officers",
                    "Cameras are already installed almost everywhere, so the video exists, "
                    "but nobody can watch it live",
                    "Review usually happens after an accident, when footage becomes evidence "
                    "rather than prevention",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "Why a bare alert is not enough",
                [
                    "Helmet missing does not say which worker, or for how long",
                    "It carries no image, so the call cannot be verified or disputed",
                    "It repeats every frame, so one violation becomes hundreds of alerts",
                    "With no record there is nothing to audit, assign or close out",
                ],
                C_RED,
            ),
            (
                "half",
                "What a safety officer actually needs",
                [
                    "A specific worker, a time range, and the named rule that was broken",
                    "The evidence crop that triggered it, so the call can be checked",
                    "An honest uncertainty state when the camera simply could not see",
                    "A plain explanation of why it matters and what to do next",
                ],
                C_GREEN,
            ),
        ],
    )


def problem_slide(prs):
    slide = blank(prs)
    title(
        slide,
        4,
        "Problem statement: from raw video to reviewable incidents",
        "Stated as one sentence, then broken into what must be seen and what must be reasoned.",
    )
    flow(
        slide,
        [
            (
                "full",
                "Precise statement",
                [
                    "Build a video-analysis system that takes pre-recorded construction "
                    "footage, detects safety hazards, tracks the worker involved, classifies "
                    "the PPE evidence, and emits incident records carrying rule, severity, "
                    "duration and an evidence crop.",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "What must be perceived",
                [
                    "Workers, and whether each wears a helmet and a high-visibility vest",
                    "Machinery and plant, so worker-to-equipment proximity can be measured",
                    "Restricted zones and elevated edges, defined once on the site plan",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "What must be reasoned about",
                [
                    "Identity across frames, so one worker is not counted as many",
                    "Duration, so a brief pass-through is not treated as sustained breach",
                    "Uncertainty, so an unreadable crop is marked unknown, not guessed",
                ],
                C_GREEN,
            ),
            (
                "half",
                "What must be produced",
                [
                    "A record with worker, rule, time range, location and evidence",
                    "A confirmed or inconclusive status that is never silently upgraded",
                    "Output stable enough for a later model to explain without re-deciding",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "Explicitly not the problem",
                [
                    "Live real-time monitoring of an operating site",
                    "Deciding legal liability or issuing a regulatory verdict",
                    "Replacing the safety officer's judgement with a model's opinion",
                ],
                C_RED,
            ),
        ],
        size=13,
    )


def foundation_slide(prs):
    slide = blank(prs)
    title(
        slide,
        5,
        "Computer vision decides; the language model only explains",
        "This boundary is what keeps the project a safety tool rather than a chatbot over footage.",
    )
    flow(
        slide,
        [
            (
                "half",
                "Computer vision owns the evidence",
                [
                    "Worker identity, time range, rule fired, location and image crop all "
                    "come from detection, tracking and the rule engine",
                    "Every field is reproducible: the same clip yields the same record",
                    "Confidence values are stored alongside the verdict, not hidden",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "The language model comes afterwards",
                [
                    "It writes the explanation, drafts the briefing and answers questions",
                    "It reads only the structured fields the pipeline already produced",
                    "It cannot create, delete or change a safety verdict",
                ],
                C_GREEN,
            ),
            (
                "half",
                "Why the order matters",
                [
                    "A model that both detects and explains cannot be audited: there is no "
                    "independent record to check its story against",
                    "Separating them means a wrong explanation is visibly wrong",
                    "It also lets us evaluate perception and language separately",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "Handling weak evidence",
                [
                    "When the crop is occluded or too small, PPE state is recorded as unknown",
                    "The incident is reported inconclusive rather than asserted",
                    "A vision model may be asked to adjudicate, but the rule still decides",
                ],
                C_RED,
            ),
        ],
        size=13,
    )


def pipeline_slide(prs):
    slide = blank(prs)
    title(
        slide,
        6,
        "Proposed computer vision pipeline",
        "Six stages run before any language model is involved.",
    )
    # 12.53 x 4.70 preserves the diagram's 16:6 aspect ratio
    slide.shapes.add_picture(
        str(CV_DIAGRAM), Inches(0.40), Inches(1.22), Inches(12.53), Inches(4.70)
    )
    note = textbox(slide, CONTENT_X, 6.06, CONTENT_W, 0.80)
    set_para(
        note.text_frame,
        "Each stage answers one question: what is in the frame, who it is over time, what "
        "they are wearing, and whether that combination breaks a rule. Nothing downstream "
        "can override an earlier stage, so every incident traces back to a specific frame "
        "and box.",
        12.5,
        color=C_BODY,
    )


def incident_slide(prs):
    slide = blank(prs)
    title(
        slide,
        7,
        "The output: a structured incident record",
        "Whenever later slides say incident, this is the object being described.",
    )
    rows = [
        ("Worker", "Track 17", "ByteTrack identity, persistent across the clip"),
        ("Rule", "R1 - helmet required", "Rule engine, evaluated over a time window"),
        ("Severity", "High", "Fixed severity attached to the rule, not inferred"),
        ("Time", "00:41.2 to 00:45.5 (4.3 s)", "Track start and end, after debounce"),
        ("Location", "Zone B, near elevated edge", "Worker box against the annotated site plan"),
        ("Evidence", "Cropped frame at 00:43.0", "Highest-confidence frame in the window"),
        ("Confidence", "detector 0.88 / PPE 0.71", "Raw model scores, stored unrounded"),
        ("Status", "Confirmed", "Becomes inconclusive if PPE state is unknown"),
    ]
    table(
        slide,
        CONTENT_X,
        1.40,
        ["Field", "Example value", "Where it comes from"],
        rows,
        [2.25, 4.30, 5.70],
        font=11.5,
        row_h=0.53,
    )
    note = textbox(slide, CONTENT_X, 6.34, CONTENT_W, 0.42)
    set_para(
        note.text_frame,
        "Every field is produced by the CV pipeline and the rule engine. The language "
        "model reads this record; it never writes to it.",
        11.5,
        color=C_SUB,
    )


def paper_slide(prs, paper):
    slide = blank(prs)
    title(
        slide,
        paper["slide"],
        paper["ref"],
        f"{paper['title']}   |   {paper['area']}",
    )
    flow(
        slide,
        [
            ("half", "Method", paper["method"], C_ACCENT),
            ("half", "Contribution", paper["contribution"], C_GREEN),
            ("half", "Limitation", paper["gap"], C_RED),
            ("half", "How we use it", paper["use"], C_ACCENT),
        ],
        size=13.5,
    )


def speaker2_synthesis(prs):
    slide = blank(prs)
    title(
        slide,
        14,
        "Detection literature gives us boxes, not incidents",
        "Closing the six PPE and detection papers: what is solved, and what is still open.",
    )
    flow(
        slide,
        [
            (
                "half",
                "What these six papers settle",
                [
                    "PPE is visually detectable at CCTV resolution, on real site imagery",
                    "Detect-then-classify beats detecting small PPE items directly",
                    "Single-stage detectors are fast and accurate enough on one GPU",
                    "Detection quality depends far more on training data than architecture",
                ],
                C_GREEN,
            ),
            (
                "half",
                "What they leave unsolved",
                [
                    "Every one of them outputs a per-frame label or box, never a record",
                    "None carries worker identity, so duration cannot be expressed",
                    "None has an uncertainty state; the classifier must always pick a class",
                    "None connects a detection to a rule, a severity or a required action",
                ],
                C_RED,
            ),
            (
                "full",
                "What we therefore build on top",
                [
                    "Take the YOLO detector and crop-classifier pattern as given, then add the "
                    "three missing pieces: a tracker for identity and duration, an explicit "
                    "unknown PPE state, and a rule engine that turns a sustained condition into "
                    "an incident record",
                ],
                C_ACCENT,
            ),
        ],
        size=13.5,
    )


def speaker3_synthesis(prs):
    slide = blank(prs)
    title(
        slide,
        21,
        "Safety rules need time, identity and context",
        "Closing the six tracking and activity papers: why one frame is never enough.",
    )
    flow(
        slide,
        [
            (
                "half",
                "What tracking contributes",
                [
                    "A stable identity, so the same worker is one subject and not many alerts",
                    "A measurable duration, which is what separates a breach from a pass-through",
                    "Recovery through occlusion, which is constant on a cluttered site",
                    "A ranked set of frames, so we can pick the clearest evidence crop",
                ],
                C_GREEN,
            ),
            (
                "half",
                "What the activity papers warn us about",
                [
                    "Site scenes are cluttered, varied and hard to label from one image",
                    "Context decides risk: the same posture is safe or unsafe by location",
                    "Per-frame classifiers cannot express how long a state persisted",
                    "Sensor-based methods work but leave no evidence a supervisor can check",
                ],
                C_RED,
            ),
            (
                "full",
                "How our rule engine responds",
                [
                    "Rules R1 to R5 take a tracked worker, a PPE state and a zone relation, then "
                    "require the condition to hold for a minimum duration before firing, with "
                    "debouncing so flicker does not create duplicate incidents",
                ],
                C_ACCENT,
            ),
        ],
        size=13.5,
    )


def gap_slide(prs):
    slide = blank(prs)
    title(
        slide,
        25,
        "No single paper delivers the whole workflow",
        "Each gap below is drawn from the survey, paired with the design decision it forced.",
    )
    rows = [
        (
            "Alerts instead of records",
            "Fang 2018 survey; Wu 2019",
            "Incident cards with worker, rule, time range and evidence crop",
        ),
        (
            "No identity or duration",
            "Nath 2020; Luo 2018",
            "ByteTrack identities plus duration thresholds in rules R1 to R5",
        ),
        (
            "Occlusion forces a guess",
            "Nath 2020; Fang 2018b",
            "An explicit unknown PPE state and an inconclusive incident status",
        ),
        (
            "No visual evidence kept",
            "Sanhudo 2021",
            "Best-frame crop stored with every incident for verification",
        ),
        (
            "No link to regulation",
            "Fang 2018 survey",
            "Retrieval-based briefing generated after the incident exists",
        ),
        (
            "Ungrounded explanation",
            "Achiam 2023; Liu 2023",
            "Guardrail, evidence-overlap check, and refusal of legal verdicts",
        ),
    ]
    table(
        slide,
        CONTENT_X,
        1.40,
        ["Gap in the literature", "Where we saw it", "Our design response"],
        rows,
        [3.45, 3.05, 5.75],
        font=11.5,
        row_h=0.68,
    )
    note = textbox(slide, CONTENT_X, 6.30, CONTENT_W, 0.45)
    set_para(
        note.text_frame,
        "The survey is not a reading list. Each of the fifteen papers either supplies a "
        "component we reuse or exposes a limitation we had to design around.",
        11.5,
        color=C_SUB,
    )


def eval_slide(prs):
    slide = blank(prs)
    title(
        slide,
        26,
        "Every component is measured on its own",
        "This prevents a weak stage from hiding behind a convincing final demo.",
    )
    rows = [
        (
            "Detection",
            "mAP@50 and mAP@50-95",
            "Held-out site frames",
            "Per-class, so small PPE objects cannot hide",
        ),
        (
            "Tracking",
            "IDF1 and identity switches",
            "Hand-checked worker tracks",
            "Switches counted manually on short clips",
        ),
        (
            "PPE head",
            "Macro-F1 and unknown rate",
            "Held-out worker crops",
            "A high unknown rate is acceptable, a wrong call is not",
        ),
        (
            "Rule engine",
            "Incident precision and recall",
            "Annotated clips",
            "Scored against human-marked incidents",
        ),
        (
            "Language layer",
            "Unsupported-claim rate",
            "Generated briefings",
            "Plus refusal rate on legal-verdict prompts",
        ),
        (
            "Usability",
            "Time to understand one incident",
            "New users",
            "Measured on a first-time reviewer, not on us",
        ),
    ]
    table(
        slide,
        CONTENT_X,
        1.40,
        ["Component", "Metric", "Evaluated on", "Why this metric"],
        rows,
        [2.15, 2.95, 2.75, 4.40],
        font=11,
        row_h=0.66,
    )
    note = textbox(slide, CONTENT_X, 6.20, CONTENT_W, 0.45)
    set_para(
        note.text_frame,
        "No results are claimed at mid-review. This slide states what we will report and "
        "on which held-out data.",
        11.5,
        color=C_SUB,
    )


def scope_slide(prs):
    slide = blank(prs)
    title(
        slide,
        27,
        "Scope and team split",
        "Four connected tracks, with the boundaries stated before we start building.",
    )
    rows = [
        (
            "Nithin H",
            "Computer vision and rules",
            "Detector fine-tuning, tracking, PPE head, rules R1 to R5",
        ),
        (
            "Pavan Kumar K N",
            "Backend and deployment",
            "Job pipeline, storage, API surface, cloud demo",
        ),
        (
            "Pranav Nayak",
            "Interface and evaluation",
            "Incident review UI, metrics harness, demo flow",
        ),
        (
            "Desu Sree Vardhan",
            "Language and retrieval",
            "Briefings, question answering, guardrails",
        ),
    ]
    table(
        slide,
        CONTENT_X,
        1.40,
        ["Member", "Track", "Responsibility"],
        rows,
        [2.95, 3.30, 6.00],
        font=11.5,
        row_h=0.58,
    )
    flow(
        slide,
        [
            (
                "half",
                "In scope this semester",
                [
                    "Pre-recorded clips processed offline, not a live feed",
                    "Rules R1 to R5 over helmet, vest, zone and proximity",
                    "A public cloud demo with a small set of annotated clips",
                ],
                C_GREEN,
            ),
            (
                "half",
                "Out of scope, deliberately",
                [
                    "Live monitoring of an operating site and alarm dispatch",
                    "Mobile application and offline edge deployment",
                    "Building-model import and enterprise access control",
                ],
                C_RED,
            ),
        ],
        size=13,
        top=4.55,
        bottom=6.90,
    )


def close_slide(prs):
    slide = blank(prs)
    title(
        slide,
        28,
        "Where we are and what comes next",
        "Closing the video on the same boundary we opened with.",
    )
    flow(
        slide,
        [
            (
                "full",
                "In one sentence",
                [
                    "Computer vision finds the incident and owns the evidence, the site view "
                    "shows where it happened, and the language model explains it without ever "
                    "deciding it.",
                ],
                C_ACCENT,
            ),
            (
                "half",
                "What this mid-review delivered",
                [
                    "A title and a problem statement narrowed to one measurable output",
                    "Fifteen papers surveyed, each mapped to a component or a gap",
                    "A pipeline design where every incident traces back to a frame",
                ],
                C_GREEN,
            ),
            (
                "half",
                "What we build before the final review",
                [
                    "Dataset split and detector fine-tuning on construction frames",
                    "PPE head with an unknown class, plus tracker integration",
                    "Rule engine producing incident cards, then the briefing layer",
                ],
                C_ACCENT,
            ),
        ],
        size=13.5,
    )


def build() -> Path:
    prs = new_prs()
    title_slide(prs)
    map_slide(prs)
    motivation_slide(prs)
    problem_slide(prs)
    foundation_slide(prs)
    pipeline_slide(prs)
    incident_slide(prs)
    for paper in PAPERS[:6]:
        paper_slide(prs, paper)
    speaker2_synthesis(prs)
    for paper in PAPERS[6:12]:
        paper_slide(prs, paper)
    speaker3_synthesis(prs)
    for paper in PAPERS[12:]:
        paper_slide(prs, paper)
    gap_slide(prs)
    eval_slide(prs)
    scope_slide(prs)
    close_slide(prs)
    prs.save(OUTPUT)
    return OUTPUT


# --- speaking script ------------------------------------------------------

FIXED_NOTES = {
    1: [
        "Give the project title, then the team and who speaks when.",
        "State the boundary immediately: computer vision decides, the language model "
        "explains. This is the sentence the whole presentation defends.",
        "Say that the mid-review focuses on the vision side because that is where the "
        "safety decision is actually made.",
    ],
    2: [
        "Walk the table quickly so the evaluators know all four of us speak for a "
        "similar length of time.",
        "Point out that the survey is not a reading list: speakers two and three each "
        "close with a synthesis slide that states what the papers left unsolved.",
    ],
    3: [
        "Start from the fact that cameras are already installed; the missing piece is "
        "not hardware, it is interpretation.",
        "Contrast the two columns directly. Read one weakness of a bare alert, then the "
        "matching need on the right. Do this for two or three pairs, not all four.",
        "Land on the idea that a safety officer needs a record, not a notification.",
    ],
    4: [
        "Read the precise statement once, slowly. It is the graded deliverable.",
        "Then use the four blocks to show the statement decomposes cleanly: what must be "
        "perceived, what must be reasoned about, what must be produced.",
        "Spend real time on the out-of-scope block. Saying what we are not doing is what "
        "makes the scope credible.",
    ],
    5: [
        "This is the most important conceptual slide. Do not rush it.",
        "Explain that if one model both detected and explained, there would be no "
        "independent record to audit its story against.",
        "Explain the weak-evidence path: unknown PPE state leads to an inconclusive "
        "incident, and the rule still decides, not the model.",
    ],
    6: [
        "Trace the diagram left to right, naming the question each stage answers: what "
        "is in the frame, who is it, what are they wearing, is that a violation.",
        "Stress that nothing downstream can override an earlier stage.",
        "Note that the language model sits entirely to the right of this diagram.",
    ],
    7: [
        "Read three or four rows, not all eight. Pick worker, time, evidence and status.",
        "Emphasise the status row: confirmed versus inconclusive, and that it is never "
        "silently upgraded.",
        "Close by saying that every later mention of an incident means this object, and "
        "hand over to speaker two.",
    ],
    14: [
        "Do not re-summarise each paper. State the two columns as a pair of claims.",
        "Left column: these six papers prove PPE is detectable and that detect-then-"
        "classify is the right shape.",
        "Right column: every one of them stops at a per-frame label, with no identity, "
        "no duration, no uncertainty and no rule.",
        "Read the bottom block as the bridge into speaker three's tracking papers.",
    ],
    21: [
        "Same structure as slide fourteen: what tracking gives us, what the activity "
        "papers warn us about.",
        "The key line is that duration is what separates a real breach from a worker "
        "walking through a zone.",
        "Use the bottom block to introduce debouncing, then hand over to speaker four.",
    ],
    25: [
        "This is the payoff slide for the whole survey. Go row by row.",
        "For each row, name the paper where we saw the gap, then the concrete design "
        "decision it forced. The pairing is what earns the literature-survey marks.",
        "Close with the note at the bottom: fifteen papers, each one either a component "
        "we reuse or a limitation we designed around.",
    ],
    26: [
        "Be explicit that we are claiming no results yet, only a measurement plan.",
        "Explain why each metric was chosen, especially the unknown rate on the PPE head: "
        "a high unknown rate is acceptable, a confident wrong call is not.",
        "Mention that usability is measured on a first-time reviewer, not on ourselves.",
    ],
    27: [
        "Read the team table quickly; the detail is on the slide.",
        "Spend the time on the two scope blocks. Out-of-scope items show we understand "
        "what a semester can actually deliver.",
    ],
    28: [
        "Read the one-sentence summary as written; it closes the loop with slide one.",
        "Name the three mid-review deliverables: title, survey, problem statement.",
        "Finish with what will be demonstrated at the final review, then thank the panel.",
    ],
}

SPEAKER_BLOCKS = [
    (
        1,
        "Nithin H",
        range(1, 8),
        "Establish the problem and the pipeline, and set the boundary between vision "
        "and language that the other three speakers rely on.",
    ),
    (
        2,
        "Pavan Kumar K N",
        range(8, 15),
        "Cover the six PPE and object-detection papers, then state what detection "
        "alone cannot deliver.",
    ),
    (
        3,
        "Pranav Nayak",
        range(15, 22),
        "Cover the six tracking, harness and activity-recognition papers, then show "
        "why rules need time, identity and context.",
    ),
    (
        4,
        "Desu Sree Vardhan",
        range(22, 29),
        "Cover the three multimodal papers, map the research gaps to design decisions, "
        "and close on evaluation, scope and next steps.",
    ),
]


def paper_notes(paper):
    def sentences(items):
        return " ".join(item.rstrip(".") + "." for item in items)

    return [
        f"Title on screen: {paper['title']}. Area: {paper['area']}.",
        "What they did: " + sentences(paper["method"]),
        "Why it matters: " + sentences(paper["contribution"]),
        "Where it stops: " + sentences(paper["gap"]),
        "How it shapes our design: " + sentences(paper["use"]),
        "Delivery: read the method column briefly, then spend your time on the "
        "limitation and the how-we-use-it column. That link is what is being graded.",
    ]


def slide_titles():
    titles = {
        1: "Title and boundary",
        2: "How the presentation is organised",
        3: "CCTV is already everywhere, but review is reactive",
        4: "Problem statement",
        5: "Vision decides, language explains",
        6: "Proposed computer vision pipeline",
        7: "The structured incident record",
        14: "Synthesis: detection gives boxes, not incidents",
        21: "Synthesis: rules need time, identity and context",
        25: "Research gaps mapped to design decisions",
        26: "Evaluation plan",
        27: "Scope and team split",
        28: "Where we are and what comes next",
    }
    for paper in PAPERS:
        titles[paper["slide"]] = paper["ref"]
    return titles


def script_text() -> str:
    titles = slide_titles()
    papers_by_slide = {p["slide"]: p for p in PAPERS}
    lines = [
        "# Mid-Review Video Script",
        "",
        "Total target: 20 to 22 minutes. Four speakers, seven slides each, about five "
        "minutes per speaker.",
        "",
        "These are speaking notes, not a word-for-word reading. Every fact below is "
        "already on the slide, so look at the panel, not the screen. The one thing worth "
        "memorising is the boundary sentence: computer vision decides, the language model "
        "explains.",
        "",
    ]
    for number, name, slides, goal in SPEAKER_BLOCKS:
        slide_list = list(slides)
        lines += [
            "---",
            "",
            f"## Speaker {number}: {name}",
            "",
            f"Slides {slide_list[0]} to {slide_list[-1]}. Target five minutes, roughly "
            f"{300 // len(slide_list)} seconds per slide.",
            "",
            f"Goal: {goal}",
            "",
        ]
        for slide_no in slide_list:
            lines += [f"### Slide {slide_no} - {titles[slide_no]}", ""]
            notes = (
                paper_notes(papers_by_slide[slide_no])
                if slide_no in papers_by_slide
                else FIXED_NOTES[slide_no]
            )
            lines += [f"- {note}" for note in notes]
            lines.append("")
    lines += [
        "---",
        "",
        "## Handover lines",
        "",
        "- Speaker 1 to 2: that is the pipeline and the record it produces. Pavan will "
        "now show which parts of it the literature already solves.",
        "- Speaker 2 to 3: detection gives us boxes. Pranav will explain why boxes on "
        "their own can never become an incident.",
        "- Speaker 3 to 4: with identity and duration in place, Sree Vardhan will cover "
        "explanation, the research gaps, and how we plan to measure all of it.",
        "- Speaker 4 close: thank the panel and offer to take questions.",
        "",
        "## If you are running long",
        "",
        "- On a paper slide, drop the method column to one sentence. Never drop the "
        "limitation or the how-we-use-it column.",
        "- On slide 7, read three rows instead of eight.",
        "- On slide 26, name the six components and one metric, and skip the reasoning.",
        "",
    ]
    return "\n".join(lines)


DOC_HEAD = RGBColor(0x2C, 0x25, 0x20)
DOC_BODY = RGBColor(0x3A, 0x35, 0x30)
DOC_ACCENT = RGBColor(0x8B, 0x5E, 0x3C)
DOC_RULE = "CCB8A8"


def _set_run(run, size, color, bold=False, italic=False):
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _bottom_rule(paragraph, color=DOC_RULE, size="12"):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    p_pr.append(borders)


def _page_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)
    _set_run(run, 9, DOC_ACCENT)


def _styled_bullet(doc, text):
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.left_indent = Cm(0.85)
    fmt.first_line_indent = Cm(-0.4)
    fmt.space_before = Pt(2)
    fmt.space_after = Pt(3)
    fmt.line_spacing = 1.08
    mark = paragraph.add_run("•  ")
    _set_run(mark, 11, DOC_ACCENT)
    label, _, rest = text.partition(": ")
    if rest and len(label) <= 42:
        lead = paragraph.add_run(label + ": ")
        _set_run(lead, 11, DOC_HEAD, bold=True)
        body = paragraph.add_run(rest)
        _set_run(body, 11, DOC_BODY)
    else:
        body = paragraph.add_run(text)
        _set_run(body, 11, DOC_BODY)
    return paragraph


def write_script_docx(markdown: str) -> Path:
    """Render the speaking script as a printable Word document."""
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(1.9)
    section.right_margin = Cm(1.9)
    section.top_margin = Cm(1.7)
    section.bottom_margin = Cm(1.6)
    section.header_distance = Cm(0.6)
    section.footer_distance = Cm(0.5)

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_run = header.add_run("Mid-review video script")
    _set_run(header_run, 9, DOC_ACCENT)
    _bottom_rule(header, size="8")

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _page_field(footer)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = DOC_BODY

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line == "---":
            continue
        if line.startswith("# "):
            title = doc.add_paragraph()
            title.paragraph_format.space_after = Pt(4)
            run = title.add_run(line[2:])
            _set_run(run, 22, DOC_HEAD, bold=True)
            _bottom_rule(title, color="8B5E3C", size="16")
            continue
        if line.startswith("## "):
            heading = doc.add_paragraph()
            if line.startswith("## Speaker ") and "Speaker 1" not in line:
                heading.paragraph_format.page_break_before = True
            heading.paragraph_format.space_before = Pt(8)
            heading.paragraph_format.space_after = Pt(2)
            run = heading.add_run(line[3:])
            _set_run(run, 16, DOC_HEAD, bold=True)
            _bottom_rule(heading)
            continue
        if line.startswith("### "):
            heading = doc.add_paragraph()
            heading.paragraph_format.space_before = Pt(12)
            heading.paragraph_format.space_after = Pt(2)
            run = heading.add_run(line[4:])
            _set_run(run, 13, DOC_ACCENT, bold=True)
            continue
        if line.startswith("- "):
            _styled_bullet(doc, line[2:])
            continue
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(4)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        paragraph.paragraph_format.line_spacing = 1.08
        label, _, rest = line.partition(": ")
        if rest and label in {"Goal"}:
            lead = paragraph.add_run(label + ": ")
            _set_run(lead, 11, DOC_HEAD, bold=True)
            body = paragraph.add_run(rest)
            _set_run(body, 11, DOC_BODY)
        else:
            body = paragraph.add_run(line)
            _set_run(body, 11, DOC_BODY, italic=line.startswith("These are speaking"))

    doc.save(SCRIPT_DOCX)
    return SCRIPT_DOCX


if __name__ == "__main__":
    output = build()
    text = script_text()
    SCRIPT.write_text(text)
    docx_path = write_script_docx(text)
    print(f"wrote {output}")
    print(f"script: {SCRIPT}")
    print(f"script docx: {docx_path}")
    print(f"slides: {len(Presentation(output).slides)}")
