from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from app.window import is_video_path
from jobs.pipeline_job import FakePipelineJob

INK = "#2a2118"
PAPER = "#f3ead8"
PANEL = "#e4d6b8"
ACCENT = "#6b4f2a"
MUTED = "#6f6454"


def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class DropWindow:
    def __init__(self, root: Path | None = None) -> None:
        self.project_root = root or Path(__file__).resolve().parents[1]
        self.output_root = self.project_root / "output"
        self._busy = False
        self.tk = tk.Tk()
        self.tk.title("Safety Twin")
        self.tk.configure(bg=PAPER)
        self.tk.minsize(640, 420)
        self.tk.geometry("720x480")
        self._build()

    def _build(self) -> None:
        pad = {"padx": 28, "pady": 8}
        tk.Label(
            self.tk,
            text="Construction Safety 2.5D Twin",
            font=("Palatino", 22),
            fg=INK,
            bg=PAPER,
        ).pack(anchor="w", padx=28, pady=(24, 0))
        tk.Label(
            self.tk,
            text="Heuristic triage — not legal advice. Distances are relative bands, not metres.",
            font=("Helvetica", 11),
            fg=MUTED,
            bg=PAPER,
            wraplength=640,
            justify="left",
        ).pack(anchor="w", **pad)

        self.zone = tk.Label(
            self.tk,
            text="Click to choose a video\n(or run: safety-twin process <file>)",
            font=("Helvetica", 14),
            fg=ACCENT,
            bg=PANEL,
            width=48,
            height=8,
            relief="ridge",
            bd=2,
            cursor="hand2",
        )
        self.zone.pack(fill="both", expand=True, padx=28, pady=12)
        self.zone.bind("<Button-1>", lambda _event: self.choose())

        self.status = tk.Label(
            self.tk,
            text="Week-1 fake pipeline. Output is a placeholder side-by-side MP4.",
            font=("Helvetica", 11),
            fg=INK,
            bg=PAPER,
            wraplength=640,
            justify="left",
        )
        self.status.pack(anchor="w", **pad)

        buttons = tk.Frame(self.tk, bg=PAPER)
        buttons.pack(fill="x", padx=28, pady=(0, 20))
        tk.Button(
            buttons,
            text="Choose video",
            command=self.choose,
            bg=ACCENT,
            fg=PAPER,
            activebackground=INK,
            activeforeground=PAPER,
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="Open output folder",
            command=lambda: _open_path(self.output_root),
            bg=PANEL,
            fg=INK,
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side="left", padx=(10, 0))

    def choose(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(
            parent=self.tk,
            title="Choose a construction-site video",
            initialdir=self.project_root / "data",
            filetypes=[
                ("Video", "*.mp4 *.mov *.mkv *.avi *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.process(Path(path))

    def process(self, video: Path) -> None:
        if self._busy:
            return
        if not is_video_path(video):
            messagebox.showerror(
                "Unsupported file",
                f"Expected a video, got {video.suffix or 'no extension'}",
            )
            return
        if not video.is_file():
            messagebox.showerror("Missing file", str(video))
            return
        self._busy = True
        self.status.configure(text=f"Processing {video.name} …")
        self.tk.update_idletasks()

        def worker() -> None:
            try:
                job = FakePipelineJob(video, output_root=self.output_root)
                manifest = job.run()
                message = (
                    f"Done {manifest.run_id}\n"
                    f"{job.run_dir / 'safety_twin.mp4'}\n"
                    "Placeholder twin — detections are synthetic."
                )
                self.tk.after(0, lambda: self._finished(job.run_dir, message))
            except Exception as exc:
                err = str(exc)
                self.tk.after(0, lambda: self._failed(err))

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, run_dir: Path, message: str) -> None:
        self._busy = False
        self.status.configure(text=message)
        _open_path(run_dir / "report.html")
        _open_path(run_dir / "safety_twin.mp4")

    def _failed(self, error: str) -> None:
        self._busy = False
        self.status.configure(text=f"Failed: {error}")
        messagebox.showerror("Process failed", error)

    def run(self) -> None:
        self.tk.mainloop()


def run_desktop() -> int:
    DropWindow().run()
    return 0
