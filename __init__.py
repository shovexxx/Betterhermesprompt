"""better-prompt — pre-audit your prompt before you send it.

Registers the agent-side surface: two slash commands, three tools, a bundled
skill and a CLI command. The deterministic audit engine lives in engine.py
(stdlib only); the AI polish uses ctx.llm with host-owned credentials.
"""

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import engine  # noqa: E402


# ---------------------------------------------------------------------------
# slash commands
# ---------------------------------------------------------------------------

def _cmd_audit(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return "Usage: /bhp-audit <prompt text>"
    r = engine.audit(raw)
    lines = [
        f"BetterPrompt score: {r.score}/100 ({r.grade})",
        "",
    ]
    if r.issues:
        for i in r.issues:
            lines.append(f"• [{i['severity']}] {i['kind']}: {i['message']}")
    else:
        lines.append("No issues found — this prompt reads clean.")
    lines.append("")
    lines.append(f"Est. {r.tokens['input_tokens']} input tokens, ~${r.tokens['est_cost_usd']} "
                 f"(model {r.tokens['model']}). Recommended template: {r.recommended_template['name']}.")
    if r.workflow:
        lines.append("") 
        for w in r.workflow[:3]:
            lines.append(f"• Workflow: {w}")
    return "\n".join(lines)


def _cmd_rewrite(ctx, raw: str):
    raw = (raw or "").strip()
    if not raw:
        return "Usage: /bhp-rewrite <prompt text>"
    r = engine.audit(raw)
    try:
        res = ctx.llm.complete_structured(
            instructions=(
                "You are a prompt engineer. Rewrite the user's draft so an agent "
                "can act on it in ONE pass: cut filler and repetition, fix typos, "
                "add the missing context/constraints as concrete clauses, and keep "
                "the original intent. Return concise JSON only."
            ),
            input=[{"type": "text", "text": raw}],
            json_schema={
                "type": "object",
                "properties": {
                    "improved": {"type": "string", "description": "The tightened, rewritten prompt."},
                    "questions": {
                        "type": "array",
                        "items": {"type": "string", "description": "A clarifying question only if truly ambiguous."},
                        "description": "Max 3. Empty when nothing is ambiguous.",
                    },
                    "why": {"type": "string", "description": "One short sentence on the biggest win."},
                },
                "required": ["improved", "questions", "why"],
            },
            schema_name="bhp.rewrite",
            purpose="better-prompt.rewrite",
            temperature=0.2,
            max_tokens=900,
        )
        if res.parsed is None:
            raise ValueError(res.text)
        p = res.parsed
        out = [f"AI-polished prompt ({res.model}):", "", p["improved"]]
        if p.get("questions"):
            out += ["", "Before sending, answer:", *[f"  {q}" for q in p["questions"]]]
        if p.get("why"):
            out += ["", f"Why: {p['why']}"]
        return "\n".join(out)
    except Exception as e:  # LLM unavailable/fail-closed -> local rewrite
        return (f"AI polish unavailable ({type(e).__name__}). Falling back to the local "
                f"zero-token rewrite:\n\n{r.rebuilded}")


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string",
                 "description": "The prompt to pre-audit before the user sends it."},
        "model": {"type": "string", "description": "Optional model id to price tokens against."},
    },
    "required": ["text"],
}

IMPROVE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The prompt draft to improve."},
    },
    "required": ["text"],
}


def _tool_audit(args: dict) -> str:
    model = args.get("model") or engine.DEFAULT_MODEL
    return json.dumps(engine.audit(args.get("text", ""), model=model).to_dict())


def _tool_improve(ctx, args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "empty prompt", "fallback": ""})
    r = engine.audit(text)
    try:
        res = ctx.llm.complete_structured(
            instructions=(
                "Prompt engineer. Tighten the draft for one-pass agent execution: "
                "cut filler, fix typos, and make missing context/constraints explicit "
                "clauses. Preserve intent. JSON only."
            ),
            input=[{"type": "text", "text": text}],
            json_schema={
                "type": "object",
                "properties": {
                    "improved": {"type": "string"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "saved_tokens": {"type": "integer"},
                },
                "required": ["improved"],
            },
            schema_name="bhp.improve",
            purpose="better-prompt.improve",
            temperature=0.2,
            max_tokens=900,
        )
        return json.dumps({
            "ok": True,
            "local_score": r.score,
            "local_tokens": r.tokens["input_tokens"],
            **({"improved": res.parsed["improved"]} if getattr(res, "parsed", None)
               else {"improved": res.text}),
            "audit": r.to_dict(),
        })
    except Exception as e:  # fail-closed LLM -> local rebuild
        return json.dumps({"ok": False, "error": str(e), "fallback": r.rebuilded,
                           "audit": r.to_dict()})


# ---------------------------------------------------------------------------
# CLI subcommand (hermes prompt-audit)
# ---------------------------------------------------------------------------

def _cli_setup(sub):
    sub.add_argument("text", nargs="*", help="Prompt text to audit (or use --file).")
    sub.add_argument("--file", help="Read the prompt from a file.")
    sub.add_argument("--rewrite", action="store_true",
                     help="Print the local zero-token rewrite too.")
    sub.add_argument("--json", action="store_true", help="Emit the full audit as JSON.")


def _cli_run(args):
    if args.file:
        raw = Path(args.file).read_text()
    elif args.text:
        raw = " ".join(args.text)
    else:
        print("No prompt given. hermes prompt-audit \"<prompt>\" or --file=...")
        return
    r = engine.audit(raw)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
        return
    print(_cmd_audit(raw))
    if args.rewrite:
        print("\n--- Local zero-token rewrite ---\n" + r.rebuilded)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

def register(ctx):
    ctx.register_command(
        name="bhp-audit", handler=_cmd_audit, args_hint="<prompt text>",
        description="Pre-audit a prompt: score, tokens/cost, typos, rambling, clarity, template.",
    )
    ctx.register_command(
        name="bhp-rewrite", handler=lambda raw: _cmd_rewrite(ctx, raw), args_hint="<prompt text>",
        description="AI-polish a prompt on your active model; returns an improved version.",
    )
    ctx.register_tool(
        name="audit_prompt", toolset="better-prompt", schema=AUDIT_SCHEMA,
        handler=_tool_audit, description="Pre-audit a prompt before sending: score, "
        "token/cost estimate, spelling + command fixes, rambling/waste flags, clarity "
        "checks, recommended template, and a local zero-token rewrite.",
        emoji="🔎",
    )
    ctx.register_tool(
        name="audit_prompt_file", toolset="better-prompt",
        schema={"type": "object", "properties": {
            "path": {"type": "string", "description": "Path to a file whose contents is the draft."},
        }, "required": ["path"]},
        handler=lambda args: _tool_audit({"text": Path(args["path"]).read_text()}),
        description="Audit a prompt draft stored in a file.",
        emoji="📄",
    )
    ctx.register_tool(
        name="improve_prompt", toolset="better-prompt", schema=IMPROVE_SCHEMA,
        handler=lambda args: _tool_improve(ctx, args),
        description="Polish a prompt on the user's active model (spends tokens); "
                    "falls back to the local zero-token rewrite if the model is unavailable.",
        emoji="✨",
    )
    ctx.register_skill(
        name="prompt-audit",
        path=str(_HERE / "skills" / "prompt-audit" / "SKILL.md"),
        description="Pre-audit prompts with the audit_prompt tool before starting long jobs.",
    )
    ctx.register_cli_command(
        name="prompt-audit",
        help="Pre-audit a prompt: score, token/cost, typos, rambling, clarity, template, rewrite.",
        description="better-prompt CLI",
        setup_fn=_cli_setup,
        handler_fn=_cli_run,
    )
