# Construction Safety 2.5D Twin

College project: drop a fixed-camera construction-site video, run offline processing, and get a side-by-side MP4 — annotated source on the left, an approximate 2.5D site twin on the right — with R1–R5 hazard cards, evidence frames, and a run report.

This is a heuristic triage tool, not a certified safety system and not legal advice. Distances are relative risk bands, not metres. The twin does not reconstruct hidden geometry or BIM.

**Status:** Week-1 fake pipeline. `safety-twin process` writes a placeholder MP4. `safety-twin app` opens a local night-desk UI (drop a clip in the browser). Real detection is not implemented.

Full specification: [`docs/plan/construction-safety-2.5d-twin-plan-v7.md`](docs/plan/construction-safety-2.5d-twin-plan-v7.md)

## Constraints

- Solo, 12 weeks, Apple M1 Pro (16 GB)
- Input: prerecorded fixed-camera video
- Output: 1920×1080 side-by-side H.264 MP4
- Twin is **2.5D**, not a surveyed reconstruction
- Gemini is optional and cached; demo must run offline
- LLM fine-tuning is a graded experiment, not the rule authority

## Hazard rules

| Id | Meaning |
|---|---|
| R1 | Apparent missing helmet |
| R2 | Apparent missing hi-vis near machinery or traffic |
| R3 | Restricted-zone intrusion |
| R4 | Approximate machinery proximity |
| R5 | Possible missing fall protection near an elevated/open edge |

## Layout

```text
app/           desktop entrypoints
jobs/          background pipeline jobs
pipeline/      intake, vision, scene, mapping, rules, render
twin/          2.5D renderer
shared/        config, coordinates, schemas
llm/           optional fine-tuning experiment
evaluation/    gates and reports
tools/         dataset fetch, CCTV intake, profilers
config/        runtime defaults
data/          local datasets (gitignored)
docs/plan/     v7 specification
```

## Setup

Requires Python 3.11.9 and [uv](https://docs.astral.sh/uv/). ffmpeg is required for the placeholder side-by-side MP4.

```bash
uv sync --group dev
uv run pytest tests/unit tests/e2e
uv run safety-twin status
uv run safety-twin process path/to/clip.mp4
uv run safety-twin app
```

`process` / `app` run the **Week-1 fake pipeline**: synthetic tracks, R1–R5 coverage, placeholder twin video, and `output/<run_id>/`. The desk UI is served at `http://127.0.0.1:8765/`. Demo clip assignments are frozen in `evaluation/demo_inventory.yaml`.

Or: `./run.sh status`

Copy `.env.example` to `.env` if you later enable Gemini scene bootstrap. The pipeline must still work with that key unset.

## Data

Datasets and working videos are local-only (about 30 GB on the development machine). Do not commit them. See [`data/README.md`](data/README.md).

```bash
python3 tools/fetch_sard.py --list complementary
python3 tools/cctv.py vet data/source/your_clip.mp4
```

## License

AGPL-3.0-or-later. Ultralytics / YOLO components used for academic open-source work require AGPL.
