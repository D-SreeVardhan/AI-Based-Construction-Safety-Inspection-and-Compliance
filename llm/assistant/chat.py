"""Risk-assessment chatbot over one run: grounded answers with checkable citations.

The model sees the run as citable facts (`pipeline/output/facts.py`), including the risk
register (`pipeline/output/risk.py`), and must cite a fact id for every claim. Every reply
is checked before it is shown:

    citations   every [ID] exists; a sentence with numbers or workers cites a fact
    numbers     each sentence's numbers are in the facts it cites (or in the question)
    names       each worker a sentence names is in the facts it cites
    verdicts    no legal verdict language (violation, illegal, breach, ...)
    pronouns    no he/she: workers are known only by track number
    units       no metric distances: the system only knows worker heights
    tone        no certainty the video cannot carry

A failing reply gets one rewrite with the failures listed. If that fails too, or no
model is configured, the answer is composed from the register itself (source
"register"), so the chatbot always answers and never invents.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from llm.assistant.providers import ChatProvider, ProviderError
from llm.guardrail import GENDERED, METRIC, OVERCLAIM, VERDICT
from pipeline.output.facts import WORKER, Fact, build_facts, register_answer, rules_in
from pipeline.output.run_bundle import RunBundle

MAX_CONTEXT_CHARS = 24_000
MAX_ANSWER_CHARS = 1_600
MAX_HISTORY = 6
CITATION = re.compile(
    r"\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?(?:\s*,\s*[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)*)\]"
)
# Never starts inside a number or an id: "I-03" and "R12" contain no claim.
NUMBER = re.compile(r"(?<![A-Za-z\-\d.])\d+(?:\.\d+)?")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.M)
NEGATION = re.compile(r"\b(no|not|none|never|nothing|neither)\b", re.I)
WORKERS = re.compile(r"\bworkers?\s+(#?\d+(?:\s*(?:,|and|&|or)\s*#?\d+)*)", re.I)

SYSTEM_PROMPT = """You are the risk-assessment assistant for one processed construction-site CCTV
clip. A site supervisor asks about hazards, workers, incidents and what to do. Answer only from
the FACTS below; they are everything known about this clip.

Rules:
- Cite the fact id in square brackets after every claim, e.g. "Worker 7 was seen without a
  helmet [I-03]."
- Use only numbers, workers, times, zones and ratings that appear in the facts. Never estimate
  or invent.
- Risk ratings come from the risk register (RISK-* facts). Quote them; never re-score.
- If the facts do not answer the question, say so plainly and suggest what to check on site.
- A rule that was "not assessed" is not "no risk": say it could not be checked and why.
- Recommend controls from the RISK-* facts, highest in the hierarchy of controls first.
- Refer to people as "worker N", never he/she. Distances are in worker heights (WH), never metres.
- This is heuristic triage from video, not legal advice: never call anything a violation, illegal,
  non-compliant or a breach.
- Be brief: at most about 150 words. Use short bullet points for lists. No preamble."""


@dataclass
class Reply:
    text: str
    source: str  # "model" | "register"
    citations: list[Fact] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    model: str | None = None
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class RiskAssistant:
    def __init__(self, bundle: RunBundle, provider: ChatProvider | None = None) -> None:
        self.bundle = bundle
        self.provider = provider
        self.facts = build_facts(bundle)
        self.by_id = {fact.id: fact for fact in self.facts}

    # ------------------------------------------------------------------ public

    def ask(self, question: str, history: Sequence[dict[str, str]] = ()) -> Reply:
        question = question.strip()[:800]
        shown = self.select(question)
        if self.provider is None:
            return self.register_answer(question)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nFACTS\n" + _format(shown)},
            *_history(history),
            {"role": "user", "content": question},
        ]
        failures: list[str] = []
        total_latency = 0.0
        for attempt in range(2):
            try:
                completion = self.provider.complete(messages)
            except ProviderError as error:
                reply = self.register_answer(question)
                reply.failures = [f"provider: {error}"]
                return reply
            total_latency += completion.latency_s
            failures = check_answer(completion.text, shown, question)
            if not failures:
                return Reply(
                    text=completion.text.strip(),
                    source="model",
                    citations=self._cited(completion.text),
                    model=completion.model,
                    latency_s=round(total_latency, 2),
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                )
            if attempt == 0:
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": "Your answer failed these checks: "
                        + "; ".join(failures)
                        + ". Rewrite it using only the facts, citing fact ids.",
                    },
                ]
        reply = self.register_answer(question)
        reply.failures = failures
        reply.latency_s = round(total_latency, 2)
        return reply

    def select(self, question: str) -> list[Fact]:
        """All run-level facts, plus the incidents that matter for this question."""
        fixed = [f for f in self.facts if f.kind not in ("incident", "worker")]
        workers = [f for f in self.facts if f.kind == "worker"]
        incidents = [f for f in self.facts if f.kind == "incident"]
        budget = MAX_CONTEXT_CHARS - sum(len(f.text) for f in fixed + workers)
        if sum(len(f.text) for f in incidents) <= budget:
            return fixed + workers + incidents
        ranked = sorted(incidents, key=lambda f: -_score(f, question))
        chosen, used = [], 0
        for fact in ranked:
            if used + len(fact.text) > budget:
                break
            chosen.append(fact)
            used += len(fact.text)
        return fixed + workers + sorted(chosen, key=lambda f: f.time_s or 0.0)

    # ------------------------------------------------------------------ fallback

    def register_answer(self, question: str) -> Reply:
        """A deterministic answer composed from the facts: no model involved."""
        text, cited = register_answer(self.bundle, self.facts, question)
        return Reply(text=text, source="register", citations=cited)

    def _cited(self, text: str) -> list[Fact]:
        ids = []
        for group in CITATION.findall(text):
            for fid in re.split(r"\s*,\s*", group):
                if fid in self.by_id and fid not in ids:
                    ids.append(fid)
        return [self.by_id[fid] for fid in ids]


# ---------------------------------------------------------------------- checks


def check_answer(text: str, shown: Sequence[Fact], question: str = "") -> list[str]:
    failures: list[str] = []
    by_id = {fact.id: fact for fact in shown}
    cited = [fid for group in CITATION.findall(text) for fid in re.split(r"\s*,\s*", group)]
    unknown = sorted({fid for fid in cited if fid not in by_id})
    if unknown:
        failures.append(f"citations: unknown fact ids {', '.join(unknown)}")
    failures += _claims(text, by_id, question)
    body = LIST_MARKER.sub("", CITATION.sub("", text))
    if VERDICT.search(body):
        failures.append("verdicts: legal or compliance verdict language")
    if GENDERED.search(body):
        failures.append("pronouns: he/she for a worker known only by number")
    if METRIC.search(body):
        failures.append("units: metric distance; only worker heights (WH) are known")
    if OVERCLAIM.search(body):
        failures.append("tone: certainty the video evidence cannot carry")
    if len(text) > MAX_ANSWER_CHARS:
        failures.append("length: answer too long")
    if not text.strip():
        failures.append("shape: empty answer")
    return failures


def _claims(text: str, by_id: dict[str, Fact], question: str) -> list[str]:
    """Each sentence's numbers and workers must be in the facts that sentence cites.

    Checking against all facts is not enough: a model can attach a true number to the wrong
    rule ("R3 had 25 incidents" when 25 is the run total) or the wrong worker. A sentence
    without a citation is covered by the next citation on the same line (one citation at
    the end of a bullet covers the bullet); a trailing uncited claim fails.
    """
    failures: list[str] = []
    asked = {_norm(n) for n in NUMBER.findall(question)}
    asked_workers = set(WORKER.findall(question))
    for line in _lines(text):
        cover: list[str] = []
        for claim in reversed(line):
            ids = [fid for g in CITATION.findall(claim) for fid in re.split(r"\s*,\s*", g)]
            cover = ids or cover
            facts = [by_id[fid] for fid in cover if fid in by_id]
            body = LIST_MARKER.sub("", CITATION.sub("", claim))
            workers = {n for group in WORKERS.findall(body) for n in re.findall(r"\d+", group)}
            numbers = {_norm(n) for n in NUMBER.findall(WORKERS.sub(" ", body))} - asked
            if not workers and not numbers:
                continue
            snippet = body.strip()[:60]
            if not facts:
                failures.append(f"citations: no citation for {snippet!r}")
                continue
            known = {_norm(n) for fact in facts for n in NUMBER.findall(fact.text)}
            stray = sorted(numbers - known, key=float)
            if stray:
                failures.append(
                    f"numbers: {', '.join(stray[:4])} not in the cited facts ({snippet!r})"
                )
            for worker in sorted(workers):
                named = any(w == worker for f in facts for w in f.workers) or any(
                    _names_worker(f.text, worker) for f in facts
                )
                # "Worker 999 has no incident [RUN]" answers the question asked
                if not named and not (worker in asked_workers and NEGATION.search(body)):
                    failures.append(f"names: worker {worker} is not in the cited facts")
    return failures


def _lines(text: str) -> list[list[str]]:
    """Sentences per line; a citation-only fragment joins the sentence before it."""
    lines: list[list[str]] = []
    for raw in text.splitlines():
        claims: list[str] = []
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z*\[(\-])", raw.strip()):
            if not part:
                continue
            if claims and not CITATION.sub("", part).strip(" .;,"):
                claims[-1] += " " + part
            else:
                claims.append(part)
        if claims:
            lines.append(claims)
    return lines


def _names_worker(text: str, worker: str) -> bool:
    return re.search(rf"\bworkers?\b[^.]*?\b{worker}\b", text, re.I) is not None


def _norm(token: str) -> str:
    return f"{round(float(token), 1):g}"


def _format(facts: Sequence[Fact]) -> str:
    return "\n".join(f"[{fact.id}] {fact.text}" for fact in facts)


def _history(history: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    turns = [
        {"role": t["role"], "content": str(t.get("content", ""))[:800]}
        for t in history
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
    ]
    return turns[-MAX_HISTORY:]


def _score(fact: Fact, question: str) -> float:
    q = question.lower()
    score = 0.0
    worker = WORKER.search(question)
    if worker and worker.group(1) in fact.workers:
        score += 10
    if fact.rule is not None and fact.rule in rules_in(q):
        score += 5
    words = set(re.findall(r"[a-z]{4,}", q))
    score += sum(1 for w in words if w in fact.text.lower())
    return score
