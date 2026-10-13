# Docs

| File | Status |
|---|---|
| [cloud-deployment.md](cloud-deployment.md) | Supabase, Hugging Face Space, publish, and verification guide |
| [plan/construction-safety-2.5d-twin-plan-v7.md](plan/construction-safety-2.5d-twin-plan-v7.md) | Current specification |
| [archive/construction-safety-digital-twin-plan.md](archive/construction-safety-digital-twin-plan.md) | Superseded earlier draft |

Implementation follows v7. The current build runs YOLO11n + ByteTrack detection, a
two-head PPE classifier reviewed by Gemini Vision, rules R1 and R2, the side-by-side twin
video, and hybrid-retrieval RAG Q&A on the Hugging Face Space. R3 to R5 still report
`unsupported_for_feed` or `inconclusive` because zone, edge and plane geometry are not
built yet. The archive file is kept for history only.
