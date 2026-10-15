# How the pipeline compares with industry practice (v3)

Written for the team and mentor. This note lists where commercial construction-safety
video analytics and open-source projects commonly fall short, and what this project does
about each gap. Vendor claims are marked as vendor claims.

## What the market offers

Commercial platforms (viAct, Intenseye, Protex AI, Everguard, Spot AI and others) run
computer vision on existing CCTV. Their common feature set is:

- PPE detection: helmet, vest, glasses;
- restricted-zone entry, with zones drawn as polygons per camera;
- proximity to heavy machinery;
- dashboards.

Reported results are case studies. For example, viAct reports a 41.7 % fall in PPE
non-compliance and 46.3 % fewer danger-zone violations in three months at one site
([Robotics 24/7](https://www.robotics247.com/article/alliad-cuts-ppe-deviations-by-42-with-viact-ai-powered-ppe-detection/technologies)).
These are vendor-reported and single-site.

Open-source work is mostly detectors and datasets, not systems:

- SH17: 8,099 images, 17 classes, manufacturing focus, best preliminary result around 70.9 % mAP
  ([arXiv 2407.04590](https://arxiv.org/abs/2407.04590v1),
  [GitHub](https://github.com/ahmadmughees/SH17dataset)).
- CHV/CHVG: hard hat colour and vest datasets
  ([PMC9299268](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9299268/),
  [GitHub](https://github.com/ZijianWang-ZW/PPE_detection)).

## Gaps, and what v3 does

| Gap seen in products and literature | Evidence | This project (v3) |
|---|---|---|
| **Alert fatigue.** Systems that fire often on non-hazards get tuned out or disabled. | [Blaxtair](https://blaxtair.com/en/wp-json/wp/v2/posts/15950), [Spot AI](https://www.spot.ai/blog/video-ai-false-alerts-construction-safety) (vendor framing), [Ardent](https://www.ardenthire.com/blog/debunking-the-myths-about-ai-cameras/) | Debounce, grace and hysteresis on video time. One incident per episode, never one alert per frame. Every incident is graded **strong / moderate / weak evidence**, and the report splits **Act now** from **Verify first**. Precision is measured by blind review (`tools/review_incidents.py`). |
| **Lagging-only counts.** Products report violations; safety practice asks for leading indicators and near-miss precursors. | [OSHA leading indicators](https://www.ecmag.com/magazine/articles/article-detail/crunching-the-safety-numbers-osha-s-leading-indicator-project), [Buildings 2024](https://doaj.org/article/472fa90871dd4e17a26e395d3242fce8) | `insights.json` and the report's **Leading indicators** section. Exposure is counted in worker-seconds per rule, per zone and per worker. **Brief exposures** (a condition that held, but for less than the debounce) are logged, as are the **closest machine approaches** whether or not an alert fired. An **exposure hotspot map** shows where on site exposure happened. |
| **Pixel-space proximity.** 2D box overlap gives false closeness through perspective. | [arXiv 2305.17931](https://arxiv.org/pdf/2305.17931), [Roboflow](https://blog.roboflow.com/preventing-accidents-on-construction-sites-with-computer-vision/) | The camera is calibrated from the workers themselves. Distances come as **worker-height intervals with 95 % bootstrap bounds** on the ground plane. A distance band is assigned only when the whole interval lies inside it; otherwise the rule says *inconclusive*. The decision trace plots that interval over time. |
| **Black-box alerts.** A user cannot see why an alert fired. | Reviews flag reliability and evaluation gaps ([Automation in Construction review](https://research.polyu.edu.hk/en/publications/computer-vision-techniques-for-construction-safety-and-health-mon/)) | Each incident carries a **decision trace**: the condition from 2 s before onset to 2 s after resolution, the signal (PPE confidence or distance interval), the debounce point, and the share of the episode the worker was visible. It is shown as "Why it fired" on every card. |
| **Stale zones.** Zones drawn at project start become wrong within weeks. | [lowcode.agency guide](https://www.lowcode.agency/blog/how-to-use-ai-to-monitor-construction-site-safety-in-real-time) | **Zone health**: every run compares each zone's area with the frame it was drawn on. It uses gradient structure, so it is robust to lighting, and flags zones whose area has changed. On SARD 9: 0.08 unchanged, 0.70 when the zone is filled in, 0.08 under a 40 % darker image. |
| **Worker surveillance and the EU AI Act.** Workplace monitoring is high-risk and requires worker notice, human oversight and logging. Emotion inference at work is banned. | [Lewis Silkin](https://www.lewissilkin.com/en/insights/2024/04/23/eu-ai-act-what-does-it-mean-for-employers), [Ogletree](https://ogletree.com/insights-resources/blog-posts/cybersecurity-awareness-month-in-focus-part-iii-the-eu-ai-act-is-here-what-it-means-for-u-s-employers/) | **Privacy by default.** Faces are pixelated in every exported frame, crop and clip. Only the face band is pixelated, so hard hats stay visible as evidence. There is no identity or biometrics, and track IDs are per clip. The report states what is and is not monitored. Humans review every incident. Provenance is recorded in the manifest (models, catalogue hash, timings). Nothing infers emotion or behaviour. |
| **Evidence is a still or a vendor clip.** | Common UI pattern | A 6–12 s annotated **evidence clip** per incident, plus the full evidence frame and an original-resolution crop. |
| **Rules apply only going forward.** | Common product limitation | `safety-twin reprocess <run>` re-runs geometry, rules and rendering on stored detections. New zones or settings take minutes, with no GPU. |
| **Unverified accuracy.** Case studies stand in for metrics, and reviews note the lack of task-specific evaluation. | [Seo et al. via PolyU](https://research.polyu.edu.hk/en/publications/computer-vision-techniques-for-construction-safety-and-health-mon/) | Blind PPE labelling (`tools/label_ppe.py`, 400 stratified crops) and incident review give precision and recall per rule and per worker size. Every rule reports *inconclusive* or *unsupported* with a reason instead of a guess. |

## What still separates this from a deployed product

- **No live mode.** It processes recorded clips offline. RTSP streaming would be the next step.
- **Single camera, single site tested.** SARD 9 is the only real footage so far.
- **No construction fine-tune of the detector.** That is blocked on the Roboflow dataset.
- **Measured accuracy pending.** The labelling tools are ready; the labels are not done.
- **Face pixelation is geometric.** It covers upright workers' face band and skips crouching
  or very small workers, whose faces are rarely identifiable.
