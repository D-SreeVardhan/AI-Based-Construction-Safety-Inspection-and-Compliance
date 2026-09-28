from __future__ import annotations

from pydantic import Field

from shared.coordinates import StrictModel
from shared.enums import RuleId


class ClauseChunk(StrictModel):
    chunk_id: str
    rule_ids: tuple[RuleId, ...]
    source: str
    clause_ref: str
    title: str
    text: str
    source_url: str
    retrieved_on: str
    sha256: str = Field(min_length=64, max_length=64)


class RetrievalHit(StrictModel):
    chunk: ClauseChunk
    score: float = Field(ge=0.0)
    lexical_score: float = Field(ge=0.0)
    semantic_hint_score: float = Field(ge=0.0)
    rank: int = Field(ge=1)


class CitedSentence(StrictModel):
    text: str
    citation_ids: tuple[str, ...]


class GroundedBriefing(StrictModel):
    incident_id: str
    rule_id: RuleId
    mode: str
    model_id: str
    retrieval_mode: str
    sentences: tuple[CitedSentence, ...]
    retrieved_chunks: tuple[RetrievalHit, ...]
    refused: bool = False
    refusal_reason: str | None = None


class RunQuestionAnswer(StrictModel):
    question: str
    answer: str
    tool_trace: tuple[str, ...]
    cited_incident_ids: tuple[str, ...] = ()
    cited_clause_ids: tuple[str, ...] = ()
    refused: bool = False
    refusal_reason: str | None = None
