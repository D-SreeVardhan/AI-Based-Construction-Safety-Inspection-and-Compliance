"""Render the 3D twin pane in a child process, in parallel with the source pane.

The twin (projection, painter's algorithm, text) costs about as much per frame as the
annotated source pane, and both are mostly Python-level drawing that holds the GIL, so
a thread does not help. A dedicated process does: the main loop hands it frame *i*'s
inputs, draws frame *i*'s source pane meanwhile, then collects the twin pane.

The renderer is stateful (trails, the slow camera sway), so one long-lived process
receives every frame in order. Shot changes are sent as a `reset` message.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
from collections.abc import Sequence
from typing import Any

import numpy as np

from shared.errors import PipelineError

RESULT_TIMEOUT_S = 60.0


def _serve(size, fps, inbox, outbox) -> None:  # pragma: no cover - runs in the child
    from pipeline.render.twin3d import TwinRenderer

    renderer = None
    while True:
        message = inbox.get()
        if message is None:
            return
        kind, payload = message
        try:
            if kind == "reset":
                mapper, proposals = payload
                renderer = TwinRenderer(size, mapper, proposals, fps=fps)
                continue
            outbox.put(("ok", renderer.render(**payload)))
        except Exception as error:  # surfaced in the parent, never swallowed
            outbox.put(("error", repr(error)))


class TwinWorker:
    def __init__(self, size: tuple[int, int], fps: float) -> None:
        context = mp.get_context("spawn")
        self._inbox = context.Queue(maxsize=2)
        self._outbox = context.Queue(maxsize=2)
        self._process = context.Process(
            target=_serve, args=(size, fps, self._inbox, self._outbox), daemon=True
        )
        self._process.start()
        self._waiting = 0

    def _put(self, message: Any) -> None:
        # Never block forever on a dead child: check it is alive while the queue is full.
        while True:
            try:
                self._inbox.put(message, timeout=1.0)
                return
            except queue.Full:
                if not self._process.is_alive():
                    raise PipelineError(
                        "TWIN_WORKER_DIED", f"exit code {self._process.exitcode}"
                    ) from None

    def reset(self, mapper: Any, proposals: Sequence[Any]) -> None:
        self._put(("reset", (mapper, tuple(proposals))))

    def submit(self, **render_kwargs: Any) -> None:
        self._put(("render", render_kwargs))
        self._waiting += 1

    def result(self) -> np.ndarray:
        if not self._waiting:
            raise RuntimeError("no twin frame was submitted")
        waited = 0.0
        while True:
            try:
                status, value = self._outbox.get(timeout=1.0)
                break
            except queue.Empty:
                waited += 1.0
                if not self._process.is_alive():
                    raise PipelineError(
                        "TWIN_WORKER_DIED", f"exit code {self._process.exitcode}"
                    ) from None
                if waited >= RESULT_TIMEOUT_S:
                    raise PipelineError(
                        "TWIN_WORKER_STALLED", f"no twin frame in {RESULT_TIMEOUT_S} s"
                    ) from None
        self._waiting -= 1
        if status != "ok":
            raise PipelineError("TWIN_WORKER_FAILED", value)
        return value

    def close(self) -> None:
        try:
            self._inbox.put(None, timeout=5)
        except queue.Full:
            pass
        self._process.join(timeout=10)
        if self._process.is_alive():
            self._process.terminate()

    def __enter__(self) -> TwinWorker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
