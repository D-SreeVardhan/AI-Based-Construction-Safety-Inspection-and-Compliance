from __future__ import annotations

from pydantic import Field

from shared.coordinates import StrictModel
from shared.enums import JobStage, ProcessingStatus


class JobRecord(StrictModel):
    schema_version: int = 1
    job_id: str
    run_id: str
    status: ProcessingStatus
    stage: JobStage
    progress: float = Field(ge=0.0, le=1.0)
    message: str = ""
    cancellable: bool = True
