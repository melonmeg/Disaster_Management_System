"""Optional LLM explanation (any OpenAI-compatible chat API, configured via LLM_*) of a deterministic ranking.

The model only receives the structured result computed by engine.evaluate() (no caller
names, phone numbers, transcripts or patient data) and must answer in a fixed JSON shape.
The answer is then checked against the real candidate data; anything that references a
unit that is not a candidate, or quotes a number that does not appear in the facts, is
rejected and the caller falls back to the plain ranking. The model never writes to MySQL.
"""
import json
import re

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config import settings

SYSTEM_PROMPT = (
    "You explain an emergency-unit ranking to a dispatcher. You are given JSON produced by a rules engine. "
    "Use ONLY facts present in that JSON. Never invent unit capabilities, distances, travel times, medical facts, "
    "incident details or resource quantities. If information is missing, say so in `limitations`. "
    "You do not decide or dispatch; the dispatcher decides. "
    "Reply with a single JSON object and nothing else: "
    '{"summary": string, "candidate_reasons": [{"unit_id": int, "reasons": [string]}], '
    '"limitations": [string], "alternatives": [int], "sufficient_evidence": boolean}. '
    "`alternatives` are unit_ids of candidates other than the top-ranked one. "
    "Set `sufficient_evidence` to false when confidence is INSUFFICIENT or LOW."
)


class CandidateReason(BaseModel):
    unit_id: int
    reasons: list[str] = Field(max_length=6)


class Explanation(BaseModel):
    summary: str = Field(min_length=1, max_length=800)
    candidate_reasons: list[CandidateReason]
    limitations: list[str] = Field(max_length=10)
    alternatives: list[int]
    sufficient_evidence: bool


class ExplanationRejected(Exception):
    pass


def facts_for_model(result: dict) -> dict:
    """The only data sent to the LLM."""
    keep = ("incident_id", "incident_type", "severity", "incident_status", "incident_location",
            "incident_coordinates", "required_unit_types", "resource_shortages", "weights", "missing", "confidence")
    cand_keys = ("rank", "unit_id", "unit_name", "unit_type", "organization_name", "base_location", "crew_size",
                 "capability_code", "distance_km", "distance_note", "relevant_stock_available", "relevant_resources", "score",
                 "confidence", "missing")
    facts = {k: result[k] for k in keep}
    facts["candidates"] = [{k: c[k] for k in cand_keys} for c in result["candidates"][:5]]
    facts["excluded_units"] = result["excluded"]
    return facts


def _numbers(text: str) -> set[float]:
    return {float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)}


def validate(raw_text: str, facts: dict) -> dict:
    """Parse the model reply and verify it against `facts`. Raises ExplanationRejected."""
    text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.S).strip()      # some models print their reasoning first
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    if not text.startswith("{") and "{" in text and "}" in text:                # JSON wrapped in prose
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Too much text is trimmed rather than rejected; invented content is still rejected below.
            if isinstance(data.get("candidate_reasons"), list):
                for cr in data["candidate_reasons"]:
                    if isinstance(cr, dict) and isinstance(cr.get("reasons"), list):
                        cr["reasons"] = cr["reasons"][:6]
            if isinstance(data.get("limitations"), list):
                data["limitations"] = data["limitations"][:10]
            if isinstance(data.get("summary"), str):
                data["summary"] = data["summary"].strip()[:800]
        explanation = Explanation.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ExplanationRejected(f"Model output does not match the expected JSON shape ({where}: {first['type']})") from exc
    except ValueError as exc:
        raise ExplanationRejected("Model output is not valid structured JSON") from exc

    candidate_ids = {c["unit_id"] for c in facts["candidates"]}
    cited = {r.unit_id for r in explanation.candidate_reasons} | set(explanation.alternatives)
    if not cited <= candidate_ids:
        raise ExplanationRejected(f"Model referenced units that are not candidates: {sorted(cited - candidate_ids)}")

    allowed = _numbers(json.dumps(facts))
    generated = " ".join([explanation.summary, *explanation.limitations,
                          *(r for cr in explanation.candidate_reasons for r in cr.reasons)])
    invented = _numbers(generated) - allowed
    if invented:
        raise ExplanationRejected(f"Model quoted numbers that are not in the supplied facts: {sorted(invented)}")

    out = explanation.model_dump()
    if facts["confidence"] in ("INSUFFICIENT", "LOW") or not facts["candidates"]:
        out["sufficient_evidence"] = False     # deterministic confidence wins over the model's opinion
    return out


def call_llm(system: str, user: str) -> str:
    """One call to an OpenAI-compatible chat-completions API (Llama API etc.); returns the reply text."""
    res = httpx.post(
        f"{settings.llm_base_url}/chat/completions", timeout=45,
        headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
        json={"model": settings.llm_model, "max_tokens": 1200, "temperature": 0,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"] or ""


def explain(result: dict) -> tuple[dict | None, str | None]:
    """Returns (explanation, None) or (None, reason it is unavailable). Never raises."""
    if not settings.llm_enabled:
        return None, "LLM explanations are disabled (LLM_ENABLED=false)"
    if not (settings.llm_api_key and settings.llm_base_url and settings.llm_model):
        return None, "No LLM configured (set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL)"
    if not result["candidates"]:
        return None, "No eligible candidates to explain"
    facts = facts_for_model(result)
    try:
        return validate(call_llm(SYSTEM_PROMPT, json.dumps(facts)), facts), None
    except ExplanationRejected as exc:
        return None, f"Generated explanation rejected: {exc}"
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        return None, f"LLM unavailable: {exc.__class__.__name__}"
