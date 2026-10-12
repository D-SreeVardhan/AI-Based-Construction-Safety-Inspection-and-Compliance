# Construction Safety 2.5D Twin
## Project Requirements & Methodology

**Submitted to:** Project Mentor
**Student:** Sreevardhan
**Duration:** 12 Weeks
**Hardware:** Apple M1 Pro, 16 GB unified memory
**Date:** September 2026

---

## 1. What We Are Building

Construction sites are one of the most hazardous work environments. Human supervisors cannot monitor every corner of a site simultaneously, and incidents like workers missing helmets, entering restricted zones, or standing too close to active machinery go undetected until it is too late.

This project builds a **desktop application** that takes a prerecorded, fixed-camera construction-site video as input and produces a **side-by-side output video** — the annotated original on the left and a synchronized **2.5D situational twin** on the right — along with structured hazard alerts, photographic evidence, and a run report.

The system detects five categories of safety hazards (labelled R1 through R5) using a combination of computer vision models, geometry estimation, and a rule engine. An optional large-language model experiment generates plain-language explanations for each alert.

**This is a heuristic triage tool — not a certified safety system and not legal advice.**

### Output at a Glance

The system produces a self-contained output folder containing:

- A 1920×1080 side-by-side video file
- A structured record of all detected hazard incidents
- A full processing manifest with all transforms and diagnostics
- A human-readable HTML run report
- A cached record of the inferred static scene zones
- Photographic evidence crops for each confirmed alert

### The Five Hazard Rules

| Rule | What It Detects |
|------|-----------------|
| R1 | Apparent missing helmet |
| R2 | Apparent missing hi-vis vest near machinery or traffic |
| R3 | Worker entering a restricted zone |
| R4 | Worker approximately within the near-machinery risk band |
| R5 | Possible missing fall protection near an elevated or open edge |

---

## 2. How We Achieve the Output — Pipeline Steps

Processing is divided into three sequential passes. Passes 2 and 3 can be re-run cheaply without repeating the expensive detection work in Pass 1.

---

### Pass 1 — Video Intake, Detection, and Tracking

**Objective:** Decode the video and extract per-frame position records for all people and machinery.

#### Step 1.1 — Video Intake and Conditioning

The application inspects the input video for codec, resolution, orientation, and camera motion. Three outcomes are possible:

- **Stable camera** — the video is used directly with no pre-processing.
- **Mild camera drift** — automatic video stabilization is applied before processing.
- **PTZ camera, scene cuts, or severe motion** — only rules R1 and R2 are evaluated; all geometry-dependent rules are marked as unsupported with a clear reason.

Portrait-orientation videos are letterboxed rather than cropped. Every detected position is internally tagged with the coordinate space it belongs to, so measurements from different processing stages are never accidentally mixed.

#### Step 1.2 — Stage 1 Detection

A YOLO object detection model runs on every frame at 15 frames per second, locating people and construction machinery including excavators, cranes, and trucks. Only detections above a minimum confidence threshold are passed to the tracker.

#### Step 1.3 — Multi-Object Tracking

ByteTrack links detections across frames to produce consistent identities over time. Each tracked entity — a person or a machine — is assigned a stable ID for the entire clip. All per-frame positions and track states are saved to a local cache on disk.

#### Step 1.4 — Stage 2 PPE Classification

Each tracked person's image crop is independently classified for two attributes:

- **Helmet:** present / not present / uncertain
- **Hi-vis vest:** present / not present / uncertain

**Uncertain** is a required, first-class outcome used when the crop is occluded, blurry, truncated, or below the confidence threshold. It is never treated as a negative detection.

A running average smooths classifications across multiple frames for each tracked person. An R1 or R2 alert requires the condition to persist for at least 1.5 seconds before triggering.

---

### Pass 2 — Mapping, Scene Bootstrap, and Rule Evaluation

**Objective:** Determine where workers and machines are in relation to each other and to static site zones, then evaluate all five hazard rules.

#### Step 2.1 — Pose Estimation and Ground-Plane Fitting

A pose estimation model estimates the positions of key body landmarks — head and ankles — on sampled frames. These measurements are used to:

1. Estimate the camera's viewing angle and the ground plane of the site.
2. Build a perspective-corrected spatial map of the scene.
3. Express all distances in **Worker-Height units (WH)** — defined as the apparent standing height of one person as seen by this camera — rather than in metres.

A Worker-Height unit is a calibration-free distance measure. Because the system uses a single fixed camera with no depth sensor and no on-site measurements, reporting distances in metres would require assumptions that cannot be verified. Using the standing height of a visible worker as the unit of distance is physically meaningful and auditable from the footage itself.

If the ground-plane fit fails due to insufficient observations, geometry-dependent rules (R4 and R5) are reported as inconclusive rather than guessing an unreliable number.

Distance uncertainty is quantified using statistical resampling. A distance band is assigned only when the full uncertainty interval falls cleanly within that band.

#### Step 2.2 — Scene Bootstrap

Static site zones — restricted areas, elevated edges, machinery operating regions, visible barriers — are inferred from a sample of 8 to 12 keyframes distributed across the clip.

**Primary path (Gemini 2.5 Flash, online):**
1. Reduced-resolution keyframes are sent to the Gemini multimodal model.
2. Gemini returns structured proposals identifying zone boundaries and zone types.
3. Proposals are cross-checked across keyframes. A zone is accepted only if it appears in at least 60% of eligible frames, with at least 5 supporting frames.
4. The result is cached against a fingerprint of the video file and all processing versions. Subsequent runs use the cache with no further API call.

**Fallback path (offline):**
When Gemini is unavailable and no cache exists, the system uses local image analysis: long-line and contour detection for possible edges, barrier detections from the Stage 1 model, and machinery position tracking. Zones identified only through this path are marked as low-confidence.

Demo videos ship with pre-generated caches, so the presentation works with no internet connection.

#### Step 2.3 — Hazard Rule Evaluation

The rule engine evaluates all five rules against the cached tracks and inferred scene state:

| Rule | Core Condition | Distance Threshold |
|------|---------------|--------------------|
| R1 | Helmet not detected, condition persists for 1.5 seconds | — |
| R2 | Hi-vis vest not detected, worker near machinery zone, persists for 1.5 seconds | — |
| R3 | Worker enters a supported restricted polygon, persists for 1.0 second | — |
| R4 | Worker within 1.5 WH of active machinery, persists for 1.0 second | 1.5 WH (near alert), 3.0 WH (caution) |
| R5 | Worker within 0.8 WH of an unguarded elevated edge, persists for 1.0 second | 0.8 WH |

Each rule returns a typed outcome: clear, alert, not applicable, inconclusive, or unsupported for this feed. All five rules remain visible in the output regardless of outcome — coverage cannot be hidden.

A 30-second cooldown per tracked person and rule prevents the same alert from firing repeatedly on a continuous condition. Alert text is generated from a fixed rule catalogue — no model invents the rule wording.

---

### Pass 3 — Rendering and Composition

**Objective:** Produce the final video and written report.

1. **2.5D twin frames** are rendered: worker markers, machinery footprints, zone polygons, and active alert overlays, all positioned using the perspective-corrected spatial map.
2. **Annotated source frames** are rendered: detection boxes, track identifiers, rule status indicators, and magnified PPE insets for confirmed incidents.
3. Both streams are composited side by side into a 1920×1080 H.264 video at 15 frames per second.
4. The HTML report, incident records, and evidence photograph crops are written to the output folder.

---

### Optional Step — LLM Fine-Tuning Experiment

This step is an academic requirement, not a safety-critical component. The application works fully without it.

**Purpose:** Test whether fine-tuning a small language model improves the quality of plain-language incident narration.

**Process:**
1. A larger teacher model (Qwen2.5-7B) generates a labelled corpus of incident records and explanations.
2. A smaller student model (Qwen2.5-1.5B) is fine-tuned on that corpus using a lightweight adaptation technique.
3. Four approaches are compared: the fixed rule template, the base student model with example prompts, the fine-tuned student, and the teacher as a reference ceiling.
4. Results are measured on: valid output format rate, unsupported-claim rate, consistency with the incident record, and response time.

If the student model produces invalid output, the application silently falls back to the fixed rule template. The language model never sets rule identifiers, severity levels, or regulatory references — those come only from the deterministic rule catalogue.

---

## 3. Chosen Models and Techniques

### 3.1 Object Detection — YOLO (Stage 1)

| Property | Choice |
|----------|--------|
| **Model** | Ultralytics YOLO26 small |
| **Input resolution** | 960 pixels |
| **Runtime** | Apple MPS (Metal) |

**Reason for choice:** YOLO26 is the current generation of Ultralytics' YOLO family. Its single-pass architecture provides the best trade-off between speed and accuracy on M1 hardware. The small variant fits within the 16 GB unified memory budget and runs at 15 frames per second. YOLO26 has strong community support, an open-source licence compatible with academic use, and native Apple Silicon acceleration via the Ultralytics library.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| RT-DETR | Higher accuracy but significantly heavier; exceeds comfortable memory headroom on M1 |
| YOLOv8 / v9 / v11 | Older revisions; YOLO26 small achieves better small-object recall on construction footage |
| EfficientDet | No first-class Apple MPS path; slower to integrate |
| Faster-RCNN | Two-stage detector; too slow for 15 fps on M1 |

---

### 3.2 Multi-Object Tracking — ByteTrack

| Property | Choice |
|----------|--------|
| **Primary tracker** | ByteTrack |
| **Fallback** | BoT-SORT |

**Reason for choice:** ByteTrack uses low-confidence detections in a second association pass, which significantly reduces track fragmentation when workers are partially occluded — a common condition on construction sites. It requires no appearance re-identification network, keeping memory and compute low on M1.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| DeepSORT | Requires a separate appearance embedding network; adds a second inference pass and memory overhead |
| BoT-SORT | More accurate in crowded scenes but more sensitive to camera motion; retained as a fallback |
| StrongSORT | Slower; heavier re-identification backbone |
| SORT | Simpler but loses track identities more often during brief occlusions |

---

### 3.3 PPE Classification — Custom Crop Classifier (Stage 2)

| Property | Choice |
|----------|--------|
| **Architecture** | Lightweight CNN with two independent output heads |
| **Input** | 224×224 pixel person crop |
| **Training set target** | Approximately 2,000 manually audited person crops |

**Reason for choice:** Running PPE classification on individual person crops is faster and more accurate than attempting to detect small helmet and vest regions in full frames. Two independent output heads allow the uncertain state to be modelled separately for each attribute. The small, audited training set is intentional — quality and domain match take priority over raw dataset size.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| End-to-end YOLO PPE detection in full frame | Struggles with small helmet and vest regions at CCTV resolution; higher missed-detection rate |
| A single combined output head | Cannot independently express "helmet uncertain, vest not detected" as a first-class outcome |
| Off-the-shelf PPE model without fine-tuning | Large domain gap between generic academic datasets and construction-site CCTV footage |

---

### 3.4 Pose Estimation — YOLO-Pose

| Property | Choice |
|----------|--------|
| **Model** | YOLO26n-Pose (nano variant) |
| **Purpose** | Head and ankle landmark detection for ground-plane fitting |
| **Sampling rate** | Every 0.5 seconds per tracked person, maximum 20 samples |

**Reason for choice:** YOLO26n-Pose shares the same backbone and runtime environment as Stage 1, avoiding a second model loading step. Head-to-ankle paired measurements provide the vertical segment observations needed to fit the ground-plane transform without requiring a depth camera. The nano variant keeps inference cost low.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| ViTPose | More accurate but significantly heavier; the extra precision is not needed for Worker-Height unit distance estimation |
| MediaPipe Pose | Not optimised for Apple MPS; produces world-coordinate output that requires additional calibration |
| Using bounding box height only | Less stable across partial occlusions; explicit ankle landmark detection is more reliable |

---

### 3.5 Scene Bootstrap — Gemini 2.5 Flash

| Property | Choice |
|----------|--------|
| **Model** | Gemini 2.5 Flash, pinned revision |
| **Call frequency** | Once per new video; results cached indefinitely |
| **Output** | Structured zone polygons and zone type labels |

**Reason for choice:** Gemini 2.5 Flash is multimodal and can reason about spatial layouts from construction-site images without requiring a separately trained segmentation or zone-detection model. At one API call per video — not per frame — the cost is negligible. Results are cached by video fingerprint so the demo always runs offline after the first call.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| Segment Anything Model (SAM) | Produces image masks but cannot interpret zone semantics or assign zone types |
| GPT-4o | Equivalent capability but higher cost and requires separate API key management |
| Training a dedicated zone-detection model | Requires a large, labelled zone dataset that does not exist publicly for construction sites |
| Local heuristics only | Retained as the offline fallback; lacks the semantic reasoning Gemini provides |

---

### 3.6 LLM Fine-Tuning — Qwen2.5

| Property | Choice |
|----------|--------|
| **Teacher model** | Qwen2.5-7B, 4-bit quantised, Apple MLX runtime |
| **Student model** | Qwen2.5-1.5B, 4-bit quantised, fine-tuned with LoRA |
| **Licence** | Apache 2.0 |

**Reason for choice:** Qwen2.5 models run natively on Apple Silicon via the MLX framework without requiring CUDA. The 1.5B student fits within the M1 memory budget alongside the running application. The Apache 2.0 licence permits academic use without restriction. The 7B teacher is used only for offline corpus generation and is never loaded at application runtime.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| Llama 3.2 1B | Slightly weaker instruction-following at this parameter count |
| Mistral 7B | Heavier; 4-bit variant still slower than Qwen2.5-7B on Apple MPS |
| Phi-3 Mini | Considered; Qwen2.5 showed better structured-output compliance in initial tests |
| Qwen2.5-3B | The required checkpoint uses a research-only licence; dropped on licence grounds |

---

### 3.7 Geometry Estimation — RANSAC Vanishing-Point Fitting

**Reason for choice:** RANSAC robustly rejects outlier observations — workers in non-standing poses, partially visible ankles — and produces a stable ground-plane estimate without requiring camera calibration data or a physical reference target in the scene. The fit diagnostics are stored in the run manifest, making the result fully auditable.

**Alternatives considered:**

| Alternative | Why Not Chosen |
|-------------|---------------|
| Metric 3D reconstruction (Structure from Motion) | Requires multiple camera viewpoints or calibration data not available from a single fixed camera |
| Monocular depth estimation (Depth Anything) | Running a dense depth model on every frame exceeds the memory and compute budget |
| Image-space normalised pixel distance | Retained as a visualisation fallback when the plane fit fails; not used to trigger R4 or R5 |

---

### 3.8 Datasets Used

Training and evaluation draw on separate, purpose-specific datasets. No dataset is used outside its intended role.

**Used for model training:**

| Dataset | Role | Licence |
|---------|------|---------|
| MJCSD | Primary Stage 1 training — CCTV-scale workers and machinery | AGPL-3.0 |
| Ultralytics Construction-PPE | Supplementary Stage 2 PPE training | AGPL-3.0 |
| jhboyo PPE (Kaggle-sourced) | Supplementary Stage 2 PPE training | MIT on the dataset card; upstream Kaggle licences independently verified |
| Custom person-crop set | Approximately 2,000 manually audited crops, seeded from the datasets above, used to train the two-head PPE classifier | Derived from the above; provenance recorded per crop |

**Used for evaluation and demonstration only — never for training:**

| Dataset | Role | Licence |
|---------|------|---------|
| SARD | Display and evaluation clips; provenance is not fully verifiable, so it is excluded from training on principle | Provenance uncertain |
| SteelBench | Holdout set for the LLM and PPE evaluation arms | CC-BY-NC-4.0 (non-commercial, consistent with academic use) |

**Operator-supplied footage:**

The developer's own recorded clips (for example, a slab-pour scene and a yard-truck scene) are used for pipeline development and end-to-end demonstration, kept locally and not committed to source control.

**Reason for this separation:** Mixing training and evaluation sources would make reported accuracy numbers unreliable, and training on SARD would violate its terms of use. Keeping a hard boundary between "trainable" and "evaluation-only" data keeps every reported metric trustworthy and every licence obligation honoured. Every dataset's exact revision, source URL, and retrieval date is recorded in a versioned licence directory before use, and again in the run manifest at processing time.

---

## 4. Documented Compromises

These are deliberate, reasoned trade-offs made within the constraints of a 12-week solo academic project. Each is recorded here so that the mentor understands the project boundaries and the rationale behind each decision.

---

### C1 — 2.5D, Not 3D

**What we give up:** True depth reconstruction, hidden geometry, BIM-grade accuracy, exact structural dimensions.
**What we gain:** A working system on a single consumer laptop with no depth camera, no multi-view rig, and no surveyed site data.
**Mitigation:** Every twin view displays the disclaimer "Approximate 2.5D visualization — positions and zones are inferred from video." Distances are reported as relative risk bands, never as metric measurements.

---

### C2 — Worker-Height Units Instead of Metres

**What we give up:** Absolute distance reporting such as "2.3 metres from the excavator."
**What we gain:** A calibration-free distance measure that is physically meaningful — one standing worker's apparent height — without requiring camera intrinsics, a known reference object, or any on-site measurement.
**Mitigation:** Band labels (near, caution, clear) convey actionable risk levels. All fitting diagnostics are stored in the run manifest so the Worker-Height unit estimate can be audited from the footage.

---

### C3 — Offline Inference Only, No Real-Time Processing

**What we give up:** Live safety monitoring; the system cannot alert supervisors in the moment.
**What we gain:** The ability to cache expensive computations and re-run only the lightweight passes when thresholds or zone definitions are adjusted. This is appropriate for a 12-week academic project.
**Mitigation:** The three-pass architecture keeps iteration fast. The mapping and rendering passes rerun in seconds without repeating the full detection work.

---

### C4 — Single Machine, Apple MPS (No CUDA)

**What we give up:** Access to CUDA-optimised model checkpoints; some models that lack Apple Silicon paths.
**What we gain:** A self-contained, portable development and demo environment with no cloud compute costs.
**Mitigation:** All model choices — YOLO26, YOLO26n-Pose, and Qwen2.5 via MLX — have verified Apple MPS paths. Peak memory usage is budgeted at 13 GB to leave headroom for the operating system and the application interface.

---

### C5 — Small PPE Training Set (Approximately 2,000 Crops)

**What we give up:** The statistical confidence of a large-scale benchmark dataset.
**What we gain:** A manually audited, domain-matched crop dataset. Every training negative is explicitly verified; the assumption that "no helmet detected equals no helmet worn" is never made silently.
**Mitigation:** The uncertain class absorbs low-confidence and ambiguous cases. Temporal smoothing over the track history further reduces noise from individual frame misclassifications.

---

### C6 — Gemini Scene Bootstrap Is Optional

**What we give up:** Rich, semantically accurate zone proposals when the API is unavailable.
**What we gain:** A demo that works completely offline with no dependency on API availability or usage quotas during the presentation.
**Mitigation:** Results are cached by video fingerprint after the first successful call. Demo videos ship with pre-generated caches. Local image analysis provides a lower-quality fallback for new videos.

---

### C7 — LLM Narration Is an Experiment, Not the Safety Authority

**What we give up:** The potential for richer, more contextual alert narrative text.
**What we gain:** A system whose safety logic is entirely deterministic and auditable. The language model generates only a short reasoning explanation and a plain-language wording of the recommended action — it never determines the rule, the severity, the basis, or the regulatory reference.
**Mitigation:** If the student model produces invalid or schema-violating output, the application uses the fixed rule template automatically and silently.

---

### C8 — SARD Footage Is Evaluation and Display Only

**What we give up:** Using real-world accident footage for model training.
**What we gain:** Compliance with SARD's terms of use, which restrict the data to research and evaluation purposes only.
**Mitigation:** Training data comes from the MJCSD dataset and open PPE datasets, each with verified provenance and compatible licences.

---

### C9 — No Authentication, Encryption, or Enterprise Features

**What we give up:** Readiness for deployment beyond a single developer machine.
**What we gain:** Full focus on the computer vision and safety logic pipeline within the 12-week timeline.
**Mitigation:** This is an academic project; the scope is explicitly bounded to the core technical challenge.

---

### C10 — Rules R3 Through R5 May Return an Inconclusive Result

**What we give up:** Complete, definitive coverage of all five rules on every input video.
**What we gain:** Honest uncertainty reporting. R3 requires a sufficiently supported zone proposal. R4 requires both a successful ground-plane fit and a confirmed active operating state for the machine. R5 requires a supported unguarded-edge proposal. When evidence is insufficient, the system reports inconclusive with a specific reason rather than guessing.
**Mitigation:** All five rules remain visible in every output with their status and reason code. Coverage reporting cannot be suppressed or hidden.

---

## 5. Summary Table

| Dimension | Chosen Approach | Key Trade-off |
|-----------|----------------|---------------|
| Detection | YOLO26 small | Speed vs. peak accuracy |
| Tracking | ByteTrack | Robustness vs. re-identification quality |
| PPE classification | Custom two-head crop classifier | Auditability vs. dataset scale |
| Pose and geometry | YOLO26n-Pose with RANSAC fitting | No calibration target required |
| Scene semantics | Gemini 2.5 Flash (cached) with local fallback | API dependency vs. semantic quality |
| Distance reporting | Worker-Height units | Calibration-free vs. metric |
| LLM narration | Qwen2.5-1.5B fine-tuned (experiment only) | Academic requirement vs. runtime reliability |
| Training data | MJCSD + open PPE datasets (trainable); SARD + SteelBench (evaluation-only) | Dataset scale vs. licence and provenance integrity |
| Output format | 1920×1080 H.264 side-by-side video | Standalone portability |
| Deployment | Local desktop, offline-first | No cloud costs or authentication complexity |

---

*All thresholds, model paths, and processing parameters are centralised in a single configuration file. No values are hardcoded inside the application logic.*

*Regulatory references (Building and Other Construction Workers Act rules) are informational and contextual. They do not constitute legal determinations.*
