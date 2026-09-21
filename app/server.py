from __future__ import annotations

import json
import posixpath
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.window import is_video_path
from jobs.pipeline_job import FakePipelineJob

WEB_ROOT = Path(__file__).resolve().parent / "web"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        if path.startswith("/static/"):
            name = path.removeprefix("/static/")
            if "/" in name or name.startswith("."):
                self.send_error(404)
                return
            file_path = WEB_ROOT / name
            self._send_file(file_path, _guess_type(file_path))
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
        try:
            upload = self._read_upload()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        suffix = Path(upload["filename"]).suffix or ".bin"
        if not is_video_path(Path(f"clip{suffix}")) and suffix != ".bin":
            self._send_json(400, {"error": f"unsupported type {suffix}"})
            return
        with tempfile.TemporaryDirectory(prefix="safety-twin-") as tmp:
            video_path = Path(tmp) / f"intake{suffix}"
            video_path.write_bytes(upload["data"])
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

    def _read_upload(self) -> dict[str, object]:
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000_000:
            raise ValueError("missing or oversized upload")
        raw = self.rfile.read(length)
        if "multipart/form-data" not in ctype or "boundary=" not in ctype:
            raise ValueError("expected multipart form upload")
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
        raise ValueError("no video field in upload")

    def _send_run_artifact(self, rest: str) -> None:
        parts = rest.split("/")
        if len(parts) != 2 or parts[0].startswith(".") or "/" in parts[1] or ".." in rest:
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
    print(f"Site Twin desk {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
