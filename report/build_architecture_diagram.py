"""Render the Section 10 architecture diagram for the CS3235 requirements document.

The diagram traces one Ask request end to end with numbered arrows, in the same
minimal style as the reference example in the course template. Arrow labels stay
deliberately short; the full explanation lives in the Section 10 prose.

    uv run python report/build_architecture_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUTPUT = Path(__file__).resolve().parent / "architecture.png"

INK = "#2B2620"
RULE = "#4A4238"
MUTED = "#6F6455"
CLOUD_EDGE = "#9A7B3F"
LOCAL_EDGE = "#7A6A55"
PAGE_BG = "#FFFFFF"
BOX_BG = "#FFFFFF"
CLOUD_BG = "#FCF8F0"
LOCAL_BG = "#F6F3ED"
LABEL_BG = "#FFFFFF"

FONT = "Helvetica Neue"


def box(ax, x, y, w, h, title, subtitle=None):
    """Draw a labelled node. x, y is the centre in axis units."""
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.6",
            facecolor=BOX_BG,
            edgecolor=RULE,
            linewidth=1.1,
            zorder=3,
        )
    )
    ax.text(
        x,
        y + (1.4 if subtitle else 0),
        title,
        ha="center",
        va="center",
        fontsize=9.0,
        color=INK,
        fontfamily=FONT,
        zorder=4,
    )
    if subtitle:
        ax.text(
            x,
            y - 2.0,
            subtitle,
            ha="center",
            va="center",
            fontsize=7.3,
            color=MUTED,
            fontfamily=FONT,
            zorder=4,
        )


def region(ax, x0, y0, x1, y1, label, edge, face):
    """Draw a dashed deployment boundary behind the nodes it contains."""
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            boxstyle="round,pad=0,rounding_size=0.8",
            facecolor=face,
            edgecolor=edge,
            linewidth=1.0,
            linestyle=(0, (5, 3)),
            zorder=1,
        )
    )
    ax.text(
        x0 + 1.6,
        y1 - 2.6,
        label,
        ha="left",
        va="center",
        fontsize=7.6,
        color=edge,
        fontfamily=FONT,
        zorder=2,
    )


def arrow(ax, start, end, label, label_xy, rad=0.0):
    """Draw a numbered flow arrow with a short label placed at label_xy."""
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            connectionstyle=f"arc3,rad={rad}",
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=0.95,
            color=RULE,
            shrinkA=1,
            shrinkB=2,
            zorder=5,
        )
    )
    ax.text(
        label_xy[0],
        label_xy[1],
        label,
        ha="center",
        va="center",
        fontsize=7.4,
        color=INK,
        fontfamily=FONT,
        zorder=6,
        bbox={"facecolor": LABEL_BG, "edgecolor": "none", "pad": 1.6},
    )


def build() -> Path:
    fig, ax = plt.subplots(figsize=(11.6, 5.6), dpi=200)
    fig.patch.set_facecolor(PAGE_BG)
    ax.set_facecolor(PAGE_BG)
    ax.set_xlim(0, 100)
    ax.set_ylim(-5, 100)
    ax.axis("off")

    # Each region is centred on its boxes: box centre == (x0 + x1) / 2, with the
    # label occupying the strip below the region's top edge.
    region(ax, 3, 6, 25, 38, "Developer laptop  ·  offline", LOCAL_EDGE, LOCAL_BG)
    region(ax, 34, 30, 57, 69, "Hugging Face Space  ·  Gradio", CLOUD_EDGE, CLOUD_BG)
    region(ax, 71, 6, 98, 69, "Supabase", CLOUD_EDGE, CLOUD_BG)

    box(ax, 14, 57.5, 22, 11, "User browser", "Gradio page")
    box(ax, 14, 26, 20, 12, "Video pipeline", "detect · PPE · rules R1–R5")
    box(ax, 14, 13, 20, 8, "Local review app", "publish button")

    box(ax, 45.5, 57.5, 21, 12, "Space app", "runs · briefings · Ask")
    box(ax, 45.5, 40, 21, 11, "Grounding check", "trigram overlap, no model")

    box(ax, 84.5, 50, 25, 14, "Postgres + pgvector", "runs · incidents · clauses")
    box(ax, 84.5, 20, 25, 12, "Supabase Storage", "private bucket · video · report")

    box(ax, 45.5, 90, 30, 11, "Gemini API", "PPE crops · scene · embeddings · answers")

    # 1-5 trace one Ask request: load the run and clauses, embed and answer, check
    # the answer, show it. Media is played from a signed URL minted per view (S).
    # A-B are the publish path from the laptop, which writes to Supabase directly.
    arrow(ax, (25, 60.5), (35, 60.5), "1  question", (30, 63.1))
    arrow(ax, (56, 59), (72, 54), "2  run + clauses", (64, 59.6))
    arrow(ax, (45.5, 63.5), (45.5, 84.5), "3  embed + answer", (45.5, 75.0))
    arrow(ax, (45.5, 51.5), (45.5, 46), "4  check", (45.5, 48.7))
    arrow(ax, (35, 54.5), (25, 54.5), "5  answer + video", (30, 51.9))
    arrow(ax, (56, 53), (72, 25), "S  sign media URL", (64, 40))

    arrow(ax, (24, 14), (72, 45), "A  publish rows", (40, 24), rad=-0.12)
    arrow(ax, (24, 11), (72, 17), "B  upload media", (52, 11.2))
    arrow(ax, (22, 32), (31, 85), "PPE crops\nkeyframes", (27.6, 44), rad=0.0)

    ax.text(
        50,
        1.6,
        "The rule engine decides what counts as a violation. The AI only explains an incident — it "
        "cannot change one.",
        ha="center",
        va="center",
        fontsize=7.5,
        color=MUTED,
        fontfamily=FONT,
        style="italic",
    )
    ax.text(
        50,
        -2.4,
        "API keys live in the local .env and the Space secrets, never in the repository and never "
        "in the browser.",
        ha="center",
        va="center",
        fontsize=7.5,
        color=MUTED,
        fontfamily=FONT,
        style="italic",
    )

    fig.savefig(OUTPUT, facecolor=PAGE_BG, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return OUTPUT


if __name__ == "__main__":
    print(f"wrote {build()}")
