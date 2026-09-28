"""Render the CV-only pipeline diagram for the mid-review presentation."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

matplotlib.use("Agg")

OUTPUT = Path(__file__).resolve().parent / "cv_pipeline.png"

PAGE_BG = "#FAFAF8"
BOX_BG = "#FFFFFF"
BOX_EDGE = "#3A3530"
ARROW_COLOR = "#6B5E52"
TITLE_COLOR = "#2C2520"
LABEL_COLOR = "#2C2520"
SUB_COLOR = "#6B5E52"
OUTPUT_BG = "#F2EDE8"
ACCENT = "#8B5E3C"
FONT = "DejaVu Sans"

W, H = 16, 6.0


def box(ax, cx, cy, w, h, title, subtitle, fill=BOX_BG):
    rect = FancyBboxPatch(
        (cx - w / 2, cy - h / 2),
        w,
        h,
        boxstyle="round,pad=0.08",
        facecolor=fill,
        edgecolor=BOX_EDGE,
        linewidth=1.4,
        zorder=3,
    )
    ax.add_patch(rect)
    for offset, line in enumerate(title.split("\n")):
        ax.text(
            cx,
            cy + 0.28 - offset * 0.34,
            line,
            ha="center",
            va="center",
            fontsize=9.2,
            fontweight="bold",
            color=LABEL_COLOR,
            fontfamily=FONT,
            zorder=4,
        )
    ax.text(
        cx,
        cy - 0.42,
        subtitle,
        ha="center",
        va="center",
        fontsize=7.2,
        color=SUB_COLOR,
        fontfamily=FONT,
        zorder=4,
    )


def arrow(ax, x0, x1, y):
    ax.add_patch(
        FancyArrowPatch(
            (x0, y),
            (x1, y),
            arrowstyle="-|>",
            color=ARROW_COLOR,
            linewidth=1.5,
            mutation_scale=14,
            zorder=2,
        )
    )


def build():
    fig, ax = plt.subplots(figsize=(W, H), facecolor=PAGE_BG)
    ax.set_facecolor(PAGE_BG)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    ax.text(
        W / 2,
        H - 0.45,
        "Computer Vision Pipeline: raw video to structured safety incidents",
        ha="center",
        va="center",
        fontsize=12.5,
        fontweight="bold",
        color=TITLE_COLOR,
        fontfamily=FONT,
    )

    cy = 3.30
    bw, bh = 2.18, 1.30
    gap = 0.40
    step = bw + gap

    stages = [
        ("Site\nVideo", "fixed CCTV\nor demo clip"),
        ("Detect\nYOLO", "workers +\nequipment"),
        ("Track\nByteTrack", "same worker\nacross frames"),
        ("Classify\nPPE", "helmet / vest\nper worker"),
        ("Evaluate\nR1-R5", "rule engine\n+ debounce"),
        ("Incident\nCards", "time, worker,\nevidence crop"),
    ]

    n = len(stages)
    total = n * bw + (n - 1) * gap
    x0 = (W - total) / 2 + bw / 2  # centre of first box

    centres = []
    for i, (title, sub) in enumerate(stages):
        cx = x0 + i * step
        centres.append(cx)
        box(ax, cx, cy, bw, bh, title, sub)

    for i in range(len(centres) - 1):
        arrow(ax, centres[i] + bw / 2, centres[i + 1] - bw / 2, cy)

    output_box = FancyBboxPatch(
        (1.1, 0.55),
        13.8,
        1.05,
        boxstyle="round,pad=0.12",
        facecolor=OUTPUT_BG,
        edgecolor=ACCENT,
        linewidth=1.1,
    )
    ax.add_patch(output_box)
    ax.text(
        W / 2,
        1.12,
        "Output used by the web app: incident ID, worker track, rule fired, severity, time range, "
        "evidence image",
        ha="center",
        va="center",
        fontsize=8.8,
        color=TITLE_COLOR,
        fontfamily=FONT,
        fontweight="bold",
    )
    ax.text(
        W / 2,
        0.72,
        "The LLM explains these incidents later. It does not decide whether the violation "
        "happened.",
        ha="center",
        va="center",
        fontsize=8,
        color=SUB_COLOR,
        fontfamily=FONT,
    )

    fig.savefig(OUTPUT, facecolor=PAGE_BG, bbox_inches="tight", pad_inches=0.08, dpi=200)
    plt.close(fig)
    return OUTPUT


if __name__ == "__main__":
    out = build()
    print(f"wrote {out}")
