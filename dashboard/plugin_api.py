"""better-prompt backend namespace — serves the Hermes Desktop half.

Exposes the deterministic audit (zero tokens), a local rewrite, and TWO AI
capabilities for the "AI polish" and "generate a better prompt" buttons:

- POST /audit      deterministic score/cost/issues (engine — no LLM)
- POST /rewrite    local zero-token rewrite (engine)
- POST /polish     AI rewrite on the user's active model (PluginLlm)
- POST /generate   AI "better prompt" construction + clarifying questions

The AI routes use the SAME host-owned facade as ctx.llm
(agent.plugin_llm.PluginLlm, constructed with this plugin id), so credentials,
model and the fail-closed trust gate are identical to an agent-side call. They
degrade to the local rewrite when the model is unavailable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from fastapi import APIRouter  # noqa: E402
import engine  # noqa: E402

router = APIRouter()

_POLISH_SCHEMA = {
    "type": "object",
    "properties": {
        "improved": {"type": "string", "description": "The tightened, rewritten prompt."},
        "questions": {
            "type": "array", "items": {"type": "string"},
            "description": "Clarifying questions for bits you could not infer. Max 3, empty when nothing is ambiguous.",
        },
        "why": {"type": "string", "description": "One short sentence on the biggest win."},
    },
    "required": ["improved", "questions", "why"],
}

_GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "improved": {"type": "string", "description": "A clean structured prompt an agent can run in one pass."},
        "template": {"type": "string", "description": "e.g. Code Task, Debug, Research, Plan, Writing, Review."},
        "questions": {
            "type": "array", "items": {"type": "string"},
            "description": "Up to 3 clarifying questions for what you could not infer.",
        },
    },
    "required": ["improved", "template", "questions"],
}


def _llm():
    from agent.plugin_llm import PluginLlm
    return PluginLlm(plugin_id="better-prompt")


def _run_structured(instructions, text, json_schema, schema_name, purpose,
                    model=None, max_tokens=900, temperature=0.2):
    """LLM call honoring the requested model when the trust gate allows it;
    otherwise uses the host's active model (fail-soft, never crashes)."""
    llm = _llm()
    inputs = [{"type": "text", "text": text}]

    def call(**extra):
        return llm.complete_structured(
            instructions=instructions,
            input=inputs,
            json_schema=json_schema,
            schema_name=schema_name,
            purpose=purpose,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )

    if model:
        try:
            return call(model=model)
        except Exception:
            pass  # trust gate / route failure → fall back to the host's active model
    return call()


@router.get("/health")
async def health():
    return {"ok": True, "plugin": "better-prompt", "engine": True}


@router.post("/audit")
async def audit(body: dict):
    """Deterministic score/cost/issue audit. No LLM call — instant, private."""
    text = (body or {}).get("text", "")
    model = (body or {}).get("model") or engine.DEFAULT_MODEL
    try:
        return {"ok": True, **engine.audit(text, model=model).to_dict()}
    except Exception as exc:  # never crash the renderer
        return {"ok": False, "error": str(exc)}


@router.post("/rewrite")
async def rewrite(body: dict):
    """Local zero-token rewrite + template recommendation."""
    text = (body or {}).get("text", "")
    if not text.strip():
        return {"ok": False, "error": "empty prompt"}
    r = engine.audit(text)
    return {"ok": True, "improved": r.rebuilded, "score": r.score,
            "template": r.recommended_template["name"]}


@router.post("/polish")
async def polish(body: dict):
    """AI rewrite on the user's active model. Falls back to the local rewrite."""
    text = (body or {}).get("text", "")
    if not text.strip():
        return {"ok": False, "error": "empty prompt"}
    local = engine.audit(text).rebuilded
    try:
        res = _run_structured(
            "You are a precise prompt editor. Fix the grammar and spelling, "
            "remove unnecessary words and filler, and tighten the user's "
            "draft so an agent can act on it in ONE pass. NEVER drop or "
            "replace the user's own request — the improved prompt must "
            "restate their actual ask in full. Preserve intent. Return JSON only.",
            text,
            _POLISH_SCHEMA, "bhp.polish", "better-prompt.polish",
            model=(body or {}).get("model") or None, max_tokens=900)
        if res.parsed:
            out = dict(res.parsed)
        else:
            out = {"improved": res.text, "questions": [], "why": res.text[:120]}
        data = {"improved": engine.light_clean(out.get("improved") or res.text),
                "questions": out.get("questions") or [], "why": out.get("why") or ""}
        return {"ok": True, "model": res.model, **data, "fallback": local}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "improved": local, "fallback": local}


@router.post("/generate")
async def generate(body: dict):
    """Build a sharper prompt + clarifying questions from a rough idea."""
    text = (body or {}).get("text", "")
    if not text.strip():
        return {"ok": False, "error": "empty prompt"}
    local = engine.rebuild(text)
    try:
        res = _run_structured(
            "You are a prompt engineer. Turn the user's rough idea into a "
            "sharply better prompt an agent can execute in one pass: a tight "
            "imperative, explicit input/scope, the expected output format, "
            "and constraints you can infer. EMBED THE USER'S IDEA VERBATIM "
            "as the goal — never return a bare template without their ask. "
            "Name the closest template (Code, "
            "Debug, Research, Plan, Writing, Review). List up to 3 genuine "
            "clarifying questions for the parts you truly cannot infer. JSON only.",
            text,
            _GENERATE_SCHEMA, "bhp.generate", "better-prompt.generate",
            model=(body or {}).get("model") or None, temperature=0.3, max_tokens=1000)
        data = res.parsed if res.parsed else {"improved": res.text, "template": "General", "questions": []}
        return {"ok": True, "model": res.model, **data, "fallback": local}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "improved": local, "template": "General", "questions": [], "fallback": local}


@router.post("/finetune")
async def finetune(body: dict):
    """Interview-then-build a targeted prompt. Deterministic build from the
    answers; optionally refined by the active model. Returns the remaining
    unanswered questions for a follow-up interview."""
    text = (body or {}).get("text", "")
    answers = (body or {}).get("answers") or {}
    built = engine.build_finetuned(answers, text)
    if not built:
        return {"ok": False, "error": "nothing to build from — answer at least one question."}
    missing = engine.finetune_missing(answers)
    # avoid echoing every field as a "question" when the build is already usable
    follow = [m for m in missing if "goal" not in m and "project" not in m][:3]
    if not answers or not built.strip():
        return {"ok": False, "error": "answer at least one question", "improved": built}
    # optional AI refinement
    refined, model, qs, err = built, None, follow, None
    try:
        res = _run_structured(
            "You are a prompt engineer. Tighten this assembled project "
            "context prompt into one crisp paragraph the agent can act on in "
            "a single pass — keep every fact, cut nothing. If a genuine "
            "ambiguous gap remains ask it (max 2). Return JSON only with "
            "'improved', 'template', 'questions'.",
            built,
            _GENERATE_SCHEMA, "bhp.finetune", "better-prompt.finetune",
            model=(body or {}).get("model") or None, max_tokens=700)
        data = res.parsed if res.parsed else {"improved": res.text, "template": "General", "questions": []}
        refined = data.get("improved") or built
        model = res.model
        qs = data.get("questions") or follow
    except Exception as exc:
        err = f"AI refine unavailable ({type(exc).__name__}); using deterministic build."
    return {"ok": True, "improved": refined, "deterministic": built,
            "questions": qs, "model": model, "error": err, "note": "Fine-tuned from interview answers."}


@router.post("/edit-offline")
async def edit_offline(body: dict):
    """Deterministic, no-AI prompt editor (spell check + better generation)."""
    text = (body or {}).get("text", "")
    if not text.strip():
        return {"ok": False, "error": "empty prompt"}
    r = engine.offline_edit(text)
    return {"ok": True, "improved": r["improved"], "changes": r["changes"],
            "score_before": r["score_before"], "score_after": r["score_after"],
            "suggestions": r.get("suggestions", []),
            "note": "Edited offline · 0 tokens · no model"}
