# Run bundle contract (v1)

The offline pipeline writes one directory per processed clip. The cloud service publishes it
(`POST /api/runs/publish`), the web UI renders it, L1 adjudicates its crops and the L3 agent
queries it. Schemas live in [`shared/schemas/bundle.py`](../../shared/schemas/bundle.py);
`pipeline.output.bundle.validate_bundle(run_dir)` checks a directory against this contract.

```text
output/<run_id>/
  run_manifest.json      RunManifest       provenance, models, R1–R8 coverage, timings, warnings
  incidents.json         IncidentsFile     confirmed incidents with catalogue-driven text
  tracks_summary.json    TracksSummaryFile per-track timelines (presence, PPE, zones, machinery bands)
  scene.json             SceneCache        restricted zones, edges, traffic zones used by R2/R3/R5
  evidence/<id>.jpg      full frame at the evidence moment, subject highlighted
  evidence/<id>_crop.jpg original-resolution person crop (L1 vision input)
  safety_twin.mp4        1920×1080 H.264 side-by-side
  safety_twin_720p.mp4   web proxy for the 720p player
  report.html            offline report
  insights.json          InsightsFile (v3, optional): leading indicators
  exposure_heatmap.jpg   where exposure happened, over the camera view (v3, optional)
  site_view.jpg          the camera view with the configured zones and edges (v3, optional)
  twin.json              worker paths, machines and zones in worker heights for the 3D viewer (v3, optional)
  evidence/<id>.mp4      annotated clip around each incident (v3, optional)
```

Exported media are privacy-filtered by default (`render.privacy: faces`): workers' face
bands are pixelated in the video, evidence frames, crops and clips. Hard hats stay
visible. The pass-1 store keeps no imagery.

Run `uv run safety-twin process <clip> --skip-video` to get a schema-complete bundle from the
synthetic pipeline today; the real pipeline writes the same files.

## Conventions

- All times are **video seconds** from the start of the clip.
- Distances are **relative worker-height units (WH)** with an interval, never metres.
- Track IDs are `shot:<shot_id>/track:<n>`; the UI label is `n` (`display_label`).
- Incident IDs are deterministic: re-processing the same clip in the same run gives the same ID.

## Incidents (`incidents.json`)

Each `IncidentRecord` is a *confirmed* alert (condition persisted past its debounce).

| Field | Meaning |
|---|---|
| `rule_id`, `title`, `severity`, `basis`, `references`, `action_code` | From `regulations/catalogue.v1.yaml` only — the LLM layers may reword, never change them |
| `first_seen_s` / `confirmed_at_s` / `resolved_at_s` | Condition start / debounce met / condition ended |
| `resolution_reason` | `condition_cleared`, `evidence_lost`, `shot_boundary`, `end_of_clip` |
| `observation_text`, `action_text` | Deterministic template text (the FR-7 fallback), written after the incident ended — states its full duration |
| `distance`, `relative_band` | R4/R5 only: WH interval and band at the closest approach |
| `object_id` | R2/R4: the machine. R7: the suspended load. R8: the fire or smoke track, which is also the incident's `canonical_track_id` (R8 has no worker subject) |
| `helmet`, `vest` | Smoothed PPE state at the evidence frame |
| `adjudication_candidate` | `true` → queue `evidence_crop_path` for L1 (PPE unknown or within 0.10 of the floor) |
| `narration` | Optional (`null` until `safety-llm narrate <run_dir>` runs). `summary`, `caveat`, `action` plus `source`: `model` when the fine-tuned narrator's text passed all eight L5 checks, `template` when it fell back; `failed_checks` names the checks a rejected reply failed. Shown instead of `observation_text` only when `source` is `model` |

Narration never changes an incident: rule, severity, references and action code stay the
catalogue's. The narrator step also records `model_ids.narrator`,
`prompt_versions.narration` and `diagnostics.narration` (model vs template counts, failed
checks, seconds) in the manifest.

### v3 incident fields

| Field | Meaning |
|---|---|
| `trace` | Why it fired. Points `{t, state: holds/clear/unknown, value, lower, upper}` from 2 s before onset to 2 s after resolution, thinned to about 5 per second (state changes always kept). `metric` is `confidence` (R1/R2/R7/R8), `distance_wh` (R4/R5) or `state` (R3/R6). `debounce_s` is the rule's debounce. `observed_fraction` is the share of the episode the subject was visible |
| `evidence_quality` | `strong` (visible at least 80 %, at least 2× debounce, confident), `weak` (visible under 50 %, or confidence within the adjudication margin of the floor), otherwise `moderate`. The UI puts weak incidents under "verify first" |
| `evidence_clip_path` | `evidence/<id>.mp4`: the annotated source pane from 2 s before to 2 s after, at most 12 s, 480 px tall |

## Leading indicators (`insights.json`)

| Field | Meaning |
|---|---|
| `exposure[]` | Per rule: `exposure_s` (worker-seconds with the hazard condition holding, confirmed or not), `workers_exposed`, `brief_exposures`, `confirmed_incidents` |
| `brief_exposures[]` | The condition held for at least 0.25 s but less than the debounce. Has rule, worker, start/end, zone or machine, and the closest distance interval (R4/R5) |
| `closest_approaches[]` | Smallest worker-to-machine (R4) or worker-to-edge (R5) distance per pair, with its interval and band, whether or not it alerted |
| `area_exposure[]` | Exposure per zone or edge, with its label and the number of workers |
| `top_workers[]` | The ten track IDs with the most exposure, split by rule. These are per-clip IDs, not identities |
| `heatmap_path` | `exposure_heatmap.jpg`, if any exposure happened |
| `zone_health` | `{proposal_id: change}`, 0 = unchanged and 1 = different, comparing the area with the frame the zone was drawn on. Values of 0.5 and above also raise a manifest warning |

## Diagnostics worth reading (`run_manifest.json → diagnostics`)

| Key | Meaning |
|---|---|
| `camera_fits.<shot>` | Camera calibrated from the workers themselves: `accepted`, `parameters` (`focal_px`, `tilt_rad`, `roll_rad`, `height_wh`), `observations`, `tracks`, `inlier_ratio`, `relative_rms` (worker-height error), `bootstrap_replicates` |
| `geometry_gate` | Whether distances are supported at all for this feed (residual camera drift in WH) |
| `pass1_seconds` | Detector, tracker and PPE time; `hard_hat_overrides` counts PPE votes vetoed by a detected hard hat |
| `narration` | See above |
| `stitching` | `tracks_before`, `identities_after`, `links`. Person tracks re-linked across occlusions (motion, size and clothing colour must agree). Every `canonical_track_id` in the bundle is the identity: the first track of its chain |

## 3D twin data (`twin.json`)

Written by `pipeline.output.twin_data.TwinRecorder` and read by the report's viewer. Positions
are on the fitted ground plane in worker heights (x right of the camera, y away from it), the
same frame as R3–R5 distances.

| Field | Meaning |
|---|---|
| `version`, `units`, `duration` | Format version (1), the unit note, clip length in seconds |
| `camera` | `height_wh`, `tilt_deg`, `roll_deg`, and `support`: the ground points the calibration saw (outside them positions are extrapolated) |
| `rules` | Bit per rule for the `rules` masks: R1 = 1 … R8 = 128 |
| `zones[]` | `id`, `label`, `type`, `line` (true for an open edge), `points` on the plane |
| `workers[]` | `id` (the stitched identity), `label`, `segments[]`. A segment breaks where the worker was unseen for over 0.6 s. Each has `t[]` (5 Hz), `xy` (flat x, y pairs, Gaussian-smoothed with σ 0.4 s), `state` (one char per sample: 0 none, 1 pending, 2 alert), `rules[]` (bitmask of active rules), `helmet` (h / n / u), `ok` (1 when the point is inside the calibrated area) |
| `machines[]` | `id`, `label`, `class`, `t[]`, `polygons[]` (footprint per sample), `state[]` (operating state) |

## Rule coverage (`run_manifest.json → rule_coverage`)

Always exactly R1–R8, in order, even when a rule could not run. Each entry has a summary
`status`, a `reason_code`, `incident_count`, and `status_counts` (subject-frames per status),
so "mostly inconclusive" is visible even when the summary says `evaluated_clear`.

| Status | Meaning |
|---|---|
| `evaluated_alert` | At least one confirmed incident |
| `evaluated_clear` | Assessed; condition not observed (or never persisted) |
| `inconclusive` | Evidence insufficient — e.g. `inconclusive_distance`, `operating_state_unknown` |
| `not_applicable` | Nothing to assess — e.g. `no_machinery_tracks`, `no_supported_restricted_zone` |
| `unsupported_for_feed` | The feed cannot support the rule — e.g. `geometry_unstable_for_feed` |

## Rule semantics worth knowing

- Timing is on video timestamps: R1/R2 debounce 1.5 s, R3–R5 and R7 1.0 s, R8 2.0 s, R6 3.0 s; a gap ≤ 0.25 s pauses the
  debounce, longer resets it; 2.0 s of clear resolves; re-triggering within 30 s reopens the
  same incident instead of creating a duplicate.
- **Inconclusive only when it matters:** a rule reports `inconclusive` only if the unknown could
  change the outcome. A worker whose whole distance interval is beyond the near band is clear
  even when the machine's operating state is unknown; a stationary machine never alerts.
- `unknown` PPE never counts as a negative, and a `no_helmet`/`no_vest` below the 0.70 floor is
  `inconclusive`, never `clear`.
- **R6–R8 are heuristic or visual** (`basis` in the catalogue). R6 alerts only on `lying`;
  a worker whose posture is unknown is `inconclusive`, never clear. R7 counts a detection as a
  load only if it is not cut off by the top of the frame and is no taller than 2.2× its width,
  which rejects crane masts. R8 alerts at confidence ≥ 0.45 and is `inconclusive` below it.
- Feeds without the pose model or the hazard prompts report R6–R8 as `unsupported_for_feed`
  (`FeedCapabilities.posture`, `FeedCapabilities.hazard_classes`).
