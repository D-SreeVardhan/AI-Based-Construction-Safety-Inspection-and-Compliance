from __future__ import annotations

import html

import gradio as gr
import spaces

from cloud.config import load_cloud_config
from cloud.media_view import (
    incident_cards_html,
    load_media,
    object_path,
    review_gallery_html,
)
from cloud.supabase import SupabaseClient
from llm.embedding_cache import get_embeddings
from llm.qa import answer_run_question
from shared.schemas.incidents import IncidentRecord
from shared.schemas.llm import GroundedBriefing
from shared.schemas.run import RuleCoverageEntry


@spaces.GPU(duration=5)
def zero_gpu_healthcheck() -> str:
    """Small registered callback required by Hugging Face ZeroGPU Spaces."""
    return "ready"


def _client() -> SupabaseClient:
    return SupabaseClient(load_cloud_config())


def _signed_media(client: SupabaseClient, stored_path: str | None) -> str | None:
    path = object_path(client, stored_path)
    if path is None:
        return None
    return client.signed_url(path)


def _video_html(url: str | None) -> str:
    # gr.Video would download the file into the Space and re-serve it; a plain
    # <video> streams straight from Supabase storage with HTTP range requests.
    if not url:
        return "<p>No twin video for this run.</p>"
    return (
        f'<video src="{html.escape(url, quote=True)}" controls preload="metadata" '
        'playsinline style="width:100%;max-height:80vh;background:#111"></video>'
    )


def list_runs() -> tuple[object, str]:
    try:
        rows = _client().select(
            "runs",
            select="id,clip_name,status,created_at",
            order="created_at.desc",
            limit=20,
        )
        choices = [row["id"] for row in rows]
        if not rows:
            return gr.update(choices=[], value=None), "No runs published yet."
        lines = [
            f"- `{row['id']}` — {row.get('clip_name', '?')} — "
            f"{row.get('status', '?')} — {row.get('created_at', '?')}"
            for row in rows
        ]
        return gr.update(choices=choices, value=choices[0]), "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return gr.update(choices=[], value=None), f"DB error: {exc}"


def load_run(run_id: str | None) -> tuple[str, str, str, str, str]:
    empty = ("", "", "", _video_html(None))
    if not run_id:
        return ("Pick a run.", *empty)
    try:
        client = _client()
        run_rows = client.select("runs", filters={"id": f"eq.{run_id}"}, limit=1)
        if not run_rows:
            return (f"No run named `{run_id}`.", *empty)
        run = run_rows[0]
        manifest = run.get("manifest") or {}
        incidents = client.select("incidents", filters={"run_id": f"eq.{run_id}"}, order="id.asc")
        briefings = client.select(
            "briefings",
            filters={"run_id": f"eq.{run_id}"},
            order="incident_id.asc",
        )
        evidence_urls, review = load_media(client, run_id)
        briefing_lines = []
        for item in briefings:
            payload = item["payload"]
            sentences = " ".join(sentence["text"] for sentence in payload.get("sentences", []))
            refs = [
                hit["chunk"]["clause_ref"]
                for hit in payload.get("retrieved_chunks", [])
                if "chunk" in hit
            ]
            briefing_lines.append(f"### {item['rule_id']}\n{sentences}\n\nCites: {', '.join(refs)}")
        cov = ", ".join(c["rule_id"] for c in manifest.get("rule_coverage", []))
        summary = (
            f"# Run `{run_id}`\n"
            f"Clip: `{run.get('clip_name', '?')}`  "
            f"Status: `{run.get('status', '?')}`  "
            f"Alerts: `{len(incidents)}`\n\n"
            f"Coverage: {cov}"
        )
        return (
            summary,
            incident_cards_html(incidents, evidence_urls),
            review_gallery_html(review),
            "\n\n".join(briefing_lines),
            _video_html(_signed_media(client, run.get("video_path"))),
        )
    except Exception as exc:  # noqa: BLE001
        return (f"Error: {exc}", *empty)


def ask_run(run_id: str | None, question: str) -> str:
    if not run_id:
        return "Pick a run first."
    if not question.strip():
        return "Enter a question."
    try:
        config = load_cloud_config()
        client = SupabaseClient(config)
        run_rows = client.select("runs", filters={"id": f"eq.{run_id}"}, limit=1)
        if not run_rows:
            return f"No run named `{run_id}`."
        manifest = run_rows[0].get("manifest") or {}
        incidents_raw = client.select("incidents", filters={"run_id": f"eq.{run_id}"})
        briefings_raw = client.select("briefings", filters={"run_id": f"eq.{run_id}"})
        coverage = tuple(
            RuleCoverageEntry.model_validate(item) for item in manifest.get("rule_coverage", [])
        )
        incidents = tuple(IncidentRecord.model_validate(item["payload"]) for item in incidents_raw)
        briefings = tuple(
            GroundedBriefing.model_validate(item["payload"]) for item in briefings_raw
        )
        answer = answer_run_question(
            question=question,
            coverage=coverage,
            incidents=incidents,
            briefings=briefings,
            gemini_api_key=config.gemini_api_key,
            embeddings=get_embeddings(),
            detection_summary=manifest.get("detection_summary") or {},
        )
        try:
            client.upsert(
                "chat_messages",
                {
                    "run_id": run_id,
                    "question": question,
                    "answer": answer.answer,
                    "payload": answer.model_dump(mode="json"),
                },
            )
        except Exception:  # noqa: BLE001
            pass
        trace = " -> ".join(answer.tool_trace)
        return f"{answer.answer}\n\nTrace: `{trace}`"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


with gr.Blocks(title="Construction Safety Twin") as demo:
    gr.Markdown(
        "# Construction Safety Twin\n"
        "> Heuristic video triage — not a certified safety system and not legal advice."
    )
    with gr.Row():
        refresh = gr.Button("Refresh runs", scale=0)
        run_picker = gr.Dropdown(label="Published runs", choices=[], scale=1)
    run_list = gr.Markdown(value="Loading…")
    twin_video = gr.HTML(label="Safety twin")
    run_summary = gr.Markdown()
    gr.Markdown("## Incidents")
    incident_cards = gr.HTML()
    gr.Markdown(
        "## PPE review crops\n"
        "Person crops sent to Gemini, with the classifier and Gemini verdicts (helmet / vest)."
    )
    review_gallery = gr.HTML()
    gr.Markdown("## Grounded briefings")
    briefings_box = gr.Markdown()
    with gr.Row():
        question_input = gr.Textbox(
            label="Ask this run",
            placeholder="Which helmet alerts were found?",
            scale=4,
        )
        ask_button = gr.Button("Ask", scale=0)
    answer_output = gr.Markdown()
    zero_gpu_probe = gr.Button("ZeroGPU healthcheck", visible=False)
    zero_gpu_status = gr.Textbox(visible=False)

    refresh.click(list_runs, outputs=[run_picker, run_list])
    run_picker.change(
        load_run,
        inputs=run_picker,
        outputs=[run_summary, incident_cards, review_gallery, briefings_box, twin_video],
    )
    ask_button.click(ask_run, inputs=[run_picker, question_input], outputs=answer_output)
    zero_gpu_probe.click(zero_gpu_healthcheck, outputs=zero_gpu_status)
    demo.load(list_runs, outputs=[run_picker, run_list])


if __name__ == "__main__":
    demo.launch()
