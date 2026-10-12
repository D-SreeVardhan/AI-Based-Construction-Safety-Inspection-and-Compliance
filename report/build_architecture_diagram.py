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
    ax.set_ylim(0, 100)
    ax.axis("off")

    # Each region is centred on its boxes: box centre == (x0 + x1) / 2, with the
    # label occupying the strip below the region's top edge.
    region(ax, 3, 14, 25, 38, "Developer laptop  ·  offline", LOCAL_EDGE, LOCAL_BG)
    region(ax, 34, 14, 57, 69, "Hugging Face Space  ·  Docker", CLOUD_EDGE, CLOUD_BG)
    region(ax, 71, 14, 98, 69, "Supabase  ·  ap-south-1", CLOUD_EDGE, CLOUD_BG)

    box(ax, 14, 57.5, 22, 11, "User browser", "web app")
    box(ax, 14, 24, 20, 12, "Video processing", "detect · track · rules R1–R5")

    box(ax, 45.5, 57.5, 21, 12, "FastAPI service", "API + web app")
    box(ax, 45.5, 40, 21, 11, "Grounding guardrail", "8 checks, no model")
    box(ax, 45.5, 24, 21, 9, "Ingest worker", "background queue")

    box(ax, 84.5, 57.5, 25, 11, "Supabase Auth", "Google sign-in")
    box(ax, 84.5, 40, 25, 12, "Postgres + pgvector", "incidents · law corpus")
    box(ax, 84.5, 23, 25, 10, "Supabase Storage", "images · video")

    box(ax, 45.5, 90, 30, 11, "Gemini 2.5 Flash", "reads images · writes answers")

    # 1-6 trace one Ask request in order: authenticate, gather context, prompt the
    # model, check the output, stream it. A-C are the separate offline publish path.
    # The API signs Storage URLs locally, so an Ask request never calls Storage; the
    # browser loads crops afterwards with the signed URL it was handed.
    arrow(ax, (25, 60.5), (35, 60.5), "1  question", (30, 63.1))
    arrow(ax, (56, 59), (72, 58), "2  check sign-in", (64, 60.8))
    arrow(ax, (56, 55), (72, 43), "3  find the clause", (64, 50.5))
    arrow(ax, (45.5, 63.5), (45.5, 84.5), "4  prompt + clause", (45.5, 75.0))
    arrow(ax, (45.5, 51.5), (45.5, 46), "5  grounding check", (45.5, 48.7))
    arrow(ax, (35, 54.5), (25, 54.5), "6  stream answer", (30, 51.9))

    arrow(ax, (24, 24), (35, 24), "A  publish", (29.5, 26.8))
    arrow(ax, (56, 27), (72, 36), "B  save incidents", (64, 32.5))
    arrow(ax, (56, 21), (72, 21), "C  save images", (64, 18.3))

    ax.text(
        50,
        6.6,
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
        2.6,
        "API keys live in the Hugging Face Space settings, never in the repository and never in "
        "the browser.",
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
