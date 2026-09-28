from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from app.server import PROJECT_ROOT, DeskHandler, resolve_local_video


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
        assert "Construction Safety Twin" in body
        assert "Drop a site video" in body
        assert "Ask this run" in body
        # Workbench order: the intake pane is authored before the output pane.
        assert body.index('id="drop"') < body.index('id="clips"')
        assert body.index('id="clips"') < body.index('id="status"')
        assert body.index('id="status"') < body.index('id="result"')

        for name, expected_type in (("styles.css", "text/css"), ("app.js", "text/javascript")):
            conn.request("GET", f"/static/{name}")
            asset = conn.getresponse()
            assert asset.status == 200
            assert expected_type in asset.getheader("Content-Type", "")
            asset.read()

        conn.request("GET", "/api/clips")
        clips = json.loads(conn.getresponse().read().decode("utf-8"))
        assert "clips" in clips

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
        first_chunk = data["briefings"][0]["retrieved_chunks"][0]["chunk"]
        assert "r1" in first_chunk["chunk_id"]

        ask_body = json.dumps({"question": "Which helmet alerts were found?"}).encode()
        conn.request(
            "POST",
            f"/api/runs/{data['run_id']}/ask",
            body=ask_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(ask_body))},
        )
        ask_response = conn.getresponse()
        answer = json.loads(ask_response.read().decode("utf-8"))
        assert ask_response.status == 200
        assert answer["refused"] is False
        assert "R1 has 1 alert" in answer["answer"]

        legal_body = json.dumps({"question": "Is this legally compliant?"}).encode()
        conn.request(
            "POST",
            f"/api/runs/{data['run_id']}/ask",
            body=legal_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(legal_body))},
        )
        legal_response = conn.getresponse()
        legal_answer = json.loads(legal_response.read().decode("utf-8"))
        assert legal_response.status == 200
        assert legal_answer["refused"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_process_local_path(tmp_path: Path) -> None:
    video = PROJECT_ROOT / "tests" / "fixtures" / "local_clip.bin"
    video.write_bytes(b"fixture")
    httpd, addr = _start(tmp_path / "output")
    try:
        conn = HTTPConnection(addr, timeout=10)
        body = json.dumps({"path": str(video)}).encode()
        conn.request(
            "POST",
            "/api/process?skip_video=1",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert data["status"] == "completed"
        assert data["briefings"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        video.unlink(missing_ok=True)


def test_desk_css_avoids_space_eating_fonts() -> None:
    # These faces ship a zero-width space glyph on some macOS installs, which
    # glues words together. Stay on the system sans/mono stacks instead.
    css = (PROJECT_ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")
    banned = ("Copperplate", "Palatino", "Iowan", "Didot", "Bodoni", "Snell", "Georgia", "Avenir")
    for name in banned:
        assert name not in css
    assert "-apple-system" in css
    assert "ui-monospace" in css


def test_desk_assets_are_self_contained() -> None:
    web = PROJECT_ROOT / "app" / "web"
    assert sorted(p.name for p in web.iterdir() if p.is_file()) == [
        "app.js",
        "index.html",
        "styles.css",
    ]
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert "@font-face" not in css
    assert "http" not in (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert "127.0.0.1:7933" not in js
    assert "X-Debug-Session-Id" not in js
    # The word-splitting DOM hack is gone; nothing should reintroduce it.
    assert "wrapWords" not in js


def test_resolve_rejects_outside_data() -> None:
    try:
        resolve_local_video("/etc/hosts")
        raise AssertionError("should reject")
    except ValueError:
        pass
