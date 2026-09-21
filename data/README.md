# Data

Local-only. Nothing under `external/`, `working/`, or `cache/` is committed.

| Path | Role | How it gets here |
|---|---|---|
| `data/source/` | Operator-supplied clips | Copy or drop files locally |
| `data/external/` | Third-party datasets (SARD, MJCSD, PPE) | `python3 tools/fetch_sard.py` and documented dataset cards |
| `data/working/` | Conditioned / stabilised feeds | `python3 tools/cctv.py condition` / `stabilise` |
| `data/cache/` | Run caches, Gemini scene cache | Created at runtime |

SARD is display/evaluation only. Do not train on it.

Current local tree (not in git):

- `data/external/sard/`
- `data/external/mjcsd/`
- `data/external/jhboyo-ppe/`
- `data/external/ultralytics-ppe/`
- `data/source/slab_pour.mp4`
- `data/source/yard_truck.mp4`
