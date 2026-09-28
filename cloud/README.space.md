---
title: Construction Safety Twin
emoji: "🏗️"
colorFrom: yellow
colorTo: red
sdk: gradio
app_file: app.py
short_description: Grounded construction safety run review
python_version: "3.11"
startup_duration_timeout: 30m
---

# Construction Safety Twin

Heuristic construction-safety video triage with grounded RAG briefings and deterministic run Q&A.

This demo is not a certified safety system, compliance determination, or legal advice.

The Space reads published run bundles from Supabase, signs private media URLs at view
time, and exposes run-scoped Q&A over incidents, rule coverage, and cited regulation
chunks. It includes a small ZeroGPU healthcheck callback because the current Space was
created with ZeroGPU hardware.
