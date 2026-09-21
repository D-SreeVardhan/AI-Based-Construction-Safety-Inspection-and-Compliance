from __future__ import annotations

import json
import posixpath
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.window import VIDEO_SUFFIXES, is_video_path
from jobs.pipeline_job import FakePipelineJob

WEB_ROOT = Path(__file__).resolve().parent / "web"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 400 * 1024 * 1024
CLIP_ROOTS = (PROJECT_ROOT / "data", PROJECT_ROOT / "tests" / "fixtures")


class DeskHandler(BaseHTTPRequestHandler):
    output_root: Path = PROJECT_ROOT / "output"
    server_version = "SafetyTwinDesk/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = posixpath.normpath(parsed.path)
        if path == "/":
            self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/clips":
            self._send_json(200, {"clips": list_local_clips()})
            return
        if path.startswith("/static/"):
            name = path.removeprefix("/static/")
            if "/" in name or name.startswith("."):
                self.send_error(404)
                return
            self._send_file(WEB_ROOT / name, _guess_type(WEB_ROOT / name))
            return
        if path.startswith("/runs/"):
            self._send_run_artifact(path.removeprefix("/runs/"))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/process":
            self.send_error(404)
            return
        skip_video = parse_qs(parsed.query).get("skip_video", ["0"])[0] == "1"
        ctype = self.headers.get("Content-Type", "")
        try:
            if ctype.startswith("application/json"):
                video_path = resolve_local_video(self._read_json()["path"])
                self._run_and_reply(video_path, skip_video=skip_video)
                return
            upload = self._read_upload()
        except (ValueError, KeyError, TypeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        suffix = Path(str(upload["filename"])).suffix or ".bin"
        if not is_video_path(Path(f"clip{suffix}")) and suffix != ".bin":
            self._send_json(400, {"error": f"Unsupported file type: {suffix}"})
            return
        with tempfile.TemporaryDirectory(prefix="safety-twin-") as tmp:
            video_path = Path(tmp) / f"intake{suffix}"
            video_path.write_bytes(upload["data"])
            self._run_and_reply(video_path, skip_video=skip_video)

    def _run_and_reply(self, video_path: Path, *, skip_video: bool) -> None:
        try:
            job = FakePipelineJob(
                video_path,
                output_root=self.output_root,
                skip_video=skip_video,
            )
            manifest = job.run()
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return
        incidents_path = job.run_dir / "incidents.json"
        incidents = json.loads(incidents_path.read_text(encoding="utf-8")).get("incidents", [])
        self._send_json(
            200,
            {
                "run_id": manifest.run_id,
                "status": manifest.status.value,
                "disclaimer": manifest.disclaimer,
                "rule_coverage": [e.model_dump(mode="json") for e in manifest.rule_coverage],
                "incidents": incidents,
                "video_url": f"/runs/{manifest.run_id}/safety_twin.mp4",
                "report_url": f"/runs/{manifest.run_id}/report.html",
            },
        )

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("Request is empty or too large.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload

    def _read_upload(self) -> dict[str, bytes | str]:
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("No file was sent.")
        if length > MAX_UPLOAD_BYTES:
            raise ValueError(
                "This file is too large to send through the browser. "
                "Paste the full file path and click Run."
            )
        raw = self.rfile.read(length)
        if "multipart/form-data" not in ctype or "boundary=" not in ctype:
            raise ValueError("Send a file upload or a JSON path.")
        boundary = ctype.split("boundary=", 1)[1].strip().encode("ascii")
        marker = b"--" + boundary
        for part in raw.split(marker):
            if b'name="video"' not in part:
                continue
            head, _, body = part.partition(b"\r\n\r\n")
            if body.endswith(b"\r\n"):
                body = body[:-2]
            filename = "upload.bin"
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-disposition"):
                    text = line.decode("utf-8", errors="replace")
                    if "filename=" in text:
                        filename = text.split("filename=", 1)[1].strip().strip('"')
            return {"filename": filename, "data": body}
        raise ValueError("No video was attached.")

    def _send_run_artifact(self, rest: str) -> None:
        parts = rest.split("/")
        if len(parts) != 2 or parts[0].startswith(".") or ".." in rest:
            self.send_error(404)
            return
        run_id, name = parts
        allowed = {"safety_twin.mp4", "report.html", "run_manifest.json", "incidents.json"}
        if name not in allowed:
            self.send_error(404)
            return
        path = self.output_root / run_id / name
        if not path.is_file():
            self.send_error(404)
            return
        self._send_file(path, _guess_type(path))

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def resolve_local_video(raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Enter a file path.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise ValueError(f"No file at {path}")
    if not is_video_path(path) and path.suffix != ".bin":
        raise ValueError("That file is not a video.")
    allowed = any(_is_relative_to(path, root.resolve()) for root in CLIP_ROOTS)
    if not allowed:
        raise ValueError("Use a video inside this project's data folder.")
    return path


def list_local_clips() -> list[dict[str, str]]:
    clips: list[dict[str, str]] = []
    for root in CLIP_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            clips.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": _size_label(path.stat().st_size),
                }
            )
    return clips


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _size_label(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB"
    if size >= 1024**2:
        return f"{size / 1024**2:.0f} MB"
    return f"{size / 1024:.0f} KB"


def _guess_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".mp4": "video/mp4",
    }.get(path.suffix, "application/octet-stream")


def serve_app(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    DeskHandler.output_root = PROJECT_ROOT / "output"
    httpd = ThreadingHTTPServer((host, port), DeskHandler)
    url = f"http://{host}:{port}/"
    print(f"Construction Safety Twin  {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
