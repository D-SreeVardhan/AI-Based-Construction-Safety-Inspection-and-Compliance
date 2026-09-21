from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from app.server import DeskHandler


def _start(output_root: Path) -> tuple[ThreadingHTTPServer, str]:
    DeskHandler.output_root = output_root
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DeskHandler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, f"{host}:{port}"


def test_index_and_process(tmp_path: Path) -> None:
    httpd, addr = _start(tmp_path / "output")
    try:
        conn = HTTPConnection(addr, timeout=10)
        conn.request("GET", "/")
        page = conn.getresponse()
        body = page.read().decode("utf-8")
        assert page.status == 200
        assert "Site Twin" in body
        assert "Drop the reel" in body

        conn.request("GET", "/static/styles.css")
        css = conn.getresponse()
        assert css.status == 200
        assert "--rust:" in css.read().decode("utf-8")

        boundary = "----twinboundary"
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="video"; filename="clip.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
            "not-a-real-video\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        conn.request(
            "POST",
            "/api/process?skip_video=1",
            body=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(payload)),
            },
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert data["status"] == "completed"
        assert [row["rule_id"] for row in data["rule_coverage"]] == ["R1", "R2", "R3", "R4", "R5"]
        assert data["incidents"]
    finally:
        httpd.shutdown()
        httpd.server_close()
