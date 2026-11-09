---
name: prompt-audit
description: >-
  Pre-audit a prompt with the audit_prompt tool before sending anything long or
  expensive. Use when the user's request is vague, rambling, expensive, prone to
  rework, or you are about to start a long multi-step task.
---

# Pre-audit prompts before you send

Wasted tokens come from prompts the agent has to loop on: vague scope, dropped
context, repeated asks, low-signal filler. This skill makes the agent check a
prompt up front and, when it is cheap, tighten it.

## When to use

Use `audit_prompt` on the user's request when **any** of these hold:

- The request is long (> ~120 words) or contains a lot of filler.
- The task is expensive (network calls, long codegen, big data, image/video).
- The intent is ambiguous ("make it better", "fix it", "do it right").
- You are about to kick off a long multi-step workflow and want to avoid rework.
- The user pasted a wall of text or a rough draft.

Do **not** audit trivial one-line asks — that spends more than it saves.

## How to audit

1. Call `audit_prompt` with the user's text.
2. Read the structured result — `score`, `issues[]`, `tokens`, and `rebuilded`.
3. High-confidence `issues` (`contradiction`, `spelling`, `vague`) are worth
   acting on: weave the missing context/constraints into what you actually run,
   or ask the ONE most important clarifying question (max one question unless
   truly blocked — the user values speed).
4. If you are about to start a long job and `score` < 60, prefer the agent-side
   `improve_prompt` tool (one LLM call) or the local `rebuilded` draft as your
   working plan, then confirm the one behavioural change with the user.

## Rules

- Never run `improve_prompt` (an LLM call) without the user's implicit consent
  for the token spend; prefer the free `rebuilded` draft or plain clarifying
  questions.
- Do not restate the whole audit back to the user — surface only the top 2-4
  issues and the single most important question. They don't want the
  ceremony.
- Preserve the user's intent. Fixing typos and filling missing context is fine;
  silently changing what they asked for is not.
- The values in the audit are estimates and heuristics, not ground truth — use
  them as working guidance.

## Reference

- Engine: the plugin's `engine.py` (stdlib-only, deterministic).
- Desktop: the BetterPrompt second prompt bar shows this audit live while you type.
- CLI: `hermes prompt-audit "<prompt>"` or `python cli.py`.
