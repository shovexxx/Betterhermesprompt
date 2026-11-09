"""better-prompt engine.

Deterministic, offline prompt pre-audit. Zero tokens spent — this whole module
runs on the user's machine with no LLM call. It estimates token usage + cost,
catches typos and mistyped commands, flags rambling / redundant / wasted-loop
instructions, checks clarity and missing context, recommends a prompt template
and workflow, and can locally rebuild a tighter draft.

Every function is a pure function of `text`; nothing here imports Hermes, so
the module is unit-testable and reusable from the CLI, the slash command, the
plugin backend, and the desktop half alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------------------
# token & cost estimation
# ---------------------------------------------------------------------------

# chars-per-token, rough per family (English prose ~4, code tighter).
CPT = {"default": 4.0}
# input + output price per 1M tokens (US $). Extend freely; misses fall to default.
# dict: model -> (input_ppm, output_ppm). If model unknown, use default_ppm.
DEFAULT_MODEL = "hermes-default"
MODEL_PRICING = {
    "gpt-4o":        (2.50, 10.00),
    "gpt-4.1-mini":  (0.40, 1.60),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4":   (1.00, 5.00),
    "deepseek-chat":  (0.27, 1.10),
    "hermes-4":       (0.20, 0.80),
    "hermes-default": (1.00, 3.00),
}


def estimate_tokens(text: str) -> int:
    """Byte-pair-flavoured approximation: merge words/punct, ~4 chars/token."""
    if not text:
        return 0
    # count prose-ish whitespace tokens then pad by chars for long code blocks
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    base = int(chars / CPT["default"])
    pen = int(words * 1.35)
    return max(1, max(base, pen))


def estimate_cost(text: str, model: str = DEFAULT_MODEL,
                  out_budget: int = 800) -> dict:
    """Return {model, input_ppm, output_ppm, input_tokens, est_output_tokens,
    est_cost_usd}. out_budget = what the reply is assumed to cost proportionally."""
    tokens = estimate_tokens(text)
    inp, out = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    est_out = out_budget  # typical answer length, headroom default
    cost_usd = (tokens / 1e6) * inp + (est_out / 1e6) * out
    return {
        "model": model,
        "input_ppm": inp,
        "output_ppm": out,
        "input_tokens": tokens,
        "est_output_tokens": est_out,
        "est_cost_usd": round(cost_usd, 6),
    }


# ---------------------------------------------------------------------------
# spelling + command dictionaries
# ---------------------------------------------------------------------------

# known Hermes slash commands (surface-agnostic core set)
HERMES_COMMANDS = [
    "help", "exit", "quit", "new", "continue", "resume", "undo", "retry",
    "memory", "remember", "forget", "skills", "tools", "model", "setup",
    "config", "skin", "theme", "tldr", "loop", "heartbeat", "checkpoint",
    "status", "doctor", "clear", "clear-ctx", "compact", "usage", "cost",
    "plugins", "mcp", "cron", "delegate", "chat", "show", "browse", "read",
    "summarize", "summarise", "image", "voice", "audio", "video", "review",
    "edit", "project", "profile", "gateway", "auth", "login", "backup",
    "import", "export", "logs", "env", "dir", "cd", "pwd", "ls", "cat",
]

SHELL_COMMANDS = [
    "ls", "cd", "pwd", "cat", "grep", "sed", "awk", "find", "cp", "mv", "rm",
    "mkdir", "touch", "chmod", "chown", "sudo", "apt", "apk", "dnf", "yum",
    "git", "curl", "wget", "python", "python3", "pip", "pip3", "uv", "node",
    "npm", "npx", "pnpm", "yarn", "docker", "tar", "zip", "unzip", "ssh",
    "scp", "rsync", "systemctl", "journalctl", "htop", "top", "free", "df",
    "du", "ps", "kill", "tail", "head", "echo", "env", "export", "source",
]

KNOWN_ALL = set(HERMES_COMMANDS).union(SHELL_COMMANDS)

# very common typos -> correction (additive, safe, high precision)
TYPO_MAP = {
    "teh": "the", "recieve": "receive", "seperate": "separate",
    "definately": "definitely", "occured": "occurred", "untill": "until",
    "wich": "which", "taht": "that", "hte": "the", "nad": "and",
    "dont": "don't", "wont": "won't", "cant": "can't", "doesnt": "doesn't",
    "wouldnt": "wouldn't", "isnt": "isn't", "arent": "aren't", "youre": "you're",
    "alot": "a lot", "i'll": "I'll", "im": "I'm", "ive": "I've", "dont't": "don't",
    "promp": "prompt", "prommpt": "prompt", "poromt": "prompt",
    "pulease": "please", "plese": "please", "thier": "their", "togther": "together",
    "becuase": "because", "becaus": "because", "writting": "writing",
    "gitignore": ".gitignore", "depdencies": "dependencies", "heirarchy": "hierarchy",
    "opreation": "operation", "configration": "configuration", "parmeter": "parameter",
    "functuin": "function", "varible": "variable", "funtion": "function",
}

# filler / hedge / rambling signal phrases (wasted tokens)
FILLER_PHRASES = [
    "basically", "kind of", "sort of", "you know", "i just", "just a quick",
    "as you know", "please note", "if that makes sense", "at the end of the day",
    "and stuff", "etc etc", "bla bla", "so basically", "right now", "very very",
    "really really", "i think i need", "i'm pretty sure", "i wanna", "gonna",
    "just want to quickly", "quick question", "sorry to bother",
]

# redundancy / double-ask patterns
REDUNDANT_PATTERNS = [
    (r"\bplease please\b", "repeated 'please'"),
    (r"\b(?:and|also)\s+then\s*$", "trailing 'and then'"),
    (r"\b(?:repeat|again)\b.*\b(?:again|repeat)\b", "double request"),
]

VAGUE_WORDS = [
    "it", "this thing", "that thing", "stuff", "things", "make it better",
    "fix it", "do it right", "i want it to work", "somehow", "whatever",
    "etc", "something", "thing", "thingy", "the usual", "like that", "and so on",
]

# punctuation-per-sentence run-on heuristic
SENT_SPLIT = re.compile(r"[.!?]+")


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def spellcheck(text: str) -> list[dict]:
    """Find likely typos. Returns [{wrong, fix, confidence}] (high-precision only)."""
    issues: list[dict] = []
    seen = set()
    # known full/repeated typo
    lowered = text.lower()
    for wrong in sorted(TYPO_MAP, key=len, reverse=True):
        if wrong in lowered and wrong not in seen:
            if len(re.findall(r"\b" + re.escape(wrong) + r"\b", lowered)):
                issues.append({"wrong": wrong, "fix": TYPO_MAP[wrong],
                               "confidence": "high", "kind": "spelling"})
                seen.add(wrong)
    # word-boundary edit-distance guessing against command vocabulary only
    for word in re.findall(r"[A-Za-z]{4,}", lowered):
        if word in KNOWN_ALL or word in seen or word in TYPO_MAP:
            continue
        best, bestd = None, 99
        for cand in KNOWN_ALL:
            d = _levenshtein(word, cand)
            if d <= 1 and len(cand) >= 4 and (d <= 1 or min(len(word), len(cand)) >= 5):
                if d < bestd:
                    best, bestd = cand, d
        if best and bestd <= 1:
            issues.append({"wrong": word, "fix": best, "confidence": "medium",
                           "kind": "spelling", "note": f"Did you mean the {best} command?"})
            seen.add(word)
    return issues


# ---------------------------------------------------------------------------
# rambling / waste / clarity
# ---------------------------------------------------------------------------

STOPWORDS = set("""
a an and are as at be by for from has have he her his i in is it its of on or
that the this to was were will with you your we our they their not no so do does
did just then what when where how who whom which can could should would must
shall may might please now also but than very really quite still even more most
""".split())

# removed for brevity, see below for use
_IGNORED = STOPWORDS


def flag_waste(text: str) -> list[dict]:
    """Return [{severity, kind, message, excerpt}] for wasted-loop / rambling."""
    flags: list[dict] = []
    lower = " " + text.lower() + " "

    filler_hits = [p for p in FILLER_PHRASES if p in lower]
    if filler_hits:
        flags.append({"severity": "medium", "kind": "filler",
                      "message": f"Filler/hedge phrases: {'; '.join(sorted(set(filler_hits)))[:140]}",
                      "excerpt": None})

    for pat, label in REDUNDANT_PATTERNS:
        m = re.search(pat, lower)
        if m:
            flags.append({"severity": "medium", "kind": "redundancy",
                          "message": label, "excerpt": m.group(0).strip()[:80]})

    words = re.findall(r"[a-z']+", lower)
    nonstop = [w for w in words if w not in STOPWORDS and len(w) > 2]
    total = len(words)
    signal = len(nonstop)
    density = signal / total if total else 0
    if signal > 60 and density < 0.42:
        flags.append({"severity": "low", "kind": "low-signal",
                      "message": f"Low information density (~{int(density*100)}% signal words). "
                                 "Trim the filler; the model burns tokens re-reading noise.",
                      "excerpt": None})

    sents = [s for s in SENT_SPLIT.split(text) if s.strip()]
    long_sents = [s.strip() for s in sents if len(s.strip().split()) > 45]
    for s in long_sents[:3]:
        flags.append({"severity": "low", "kind": "run-on",
                      "message": f"Run-on sentence ({len(s.split())} words). Split it into concrete steps.",
                      "excerpt": s[:120]})

    action_verbs = len(re.findall(r"\b(iterate|rerun|retry|do it again|start over|resp\\ble)\b", lower))
    # repeated equivalent asks
    repetition = _repeated_verbs(text)
    if repetition:
        flags.append({"severity": "low", "kind": "repetition",
                      "message": repetition, "excerpt": None})

    contradictory = _contradiction(text)
    if contradictory:
        flags.append({"severity": "high", "kind": "contradiction",
                      "message": contradictory, "excerpt": None})

    if action_verbs >= 3:
        flags.append({"severity": "low", "kind": "loop-hint",
                      "message": "Looks like you're describing a retry/iterate loop. "
                                 "State each step ONCE and give the exit condition."})
    return flags


def _repeated_verbs(text: str) -> str | None:
    verbs = re.findall(
        r"\b(add|create|update|fix|remove|delete|make|write|read|list|describe|"
        r"check|run|install|build|summarize|summarise|convert|move|copy)\b",
        text.lower())
    from collections import Counter
    top = Counter(verbs).most_common(1)
    if top and top[0][1] >= 3:
        return f"The verb \"{top[0][0]}\" repeats {top[0][1]}× — chances you're asking for the same thing more than once."
    return None


def _contradiction(text: str) -> str | None:
    lower = text.lower()
    pairs = [
        ("delete", "keep"), ("remove", "preserve"), ("don't", "do "),
        ("never", "always"), ("stop", "start"), ("hide", "show"),
    ]
    for a, b in pairs:
        if a in lower and b in lower:
            return f"Possible contradiction: `{a}` and `{b}` both appear. Make the call explicit."
    return None


def clarity_checks(text: str) -> list[dict]:
    """Missing-context checklist -> [{severity, kind, question}] plus a deterministic
    clarifying question set. Returns issues with a 'question' for the UI."""
    checks: list[dict] = []
    lower = text.lower()

    def note(severity: str, kind: str, question: str):
        checks.append({"severity": severity, "kind": kind, "question": question})

    if not re.search(r"@\S+|/files|cwd|the file|this repo|at \S+|in \S+|/\S+", text):
        note("medium", "input-context",
             "What is the input / where does this task operate? (file, folder, repo, URL, pasted data?)")
    if not re.search(r"\b(output|result|return|report|artifact|format|as (json|md|csv|table)|schema)\b", lower):
        note("medium", "output-format",
             "What should the output look like? (JSON, markdown, code block, a file, just a yes/no?)")
    if not re.search(r"\b(limit|only|don't|do not|must not|must |exactly|no more than|without|unless|except|require|constraint|boundary)\b", lower):
        note("low", "constraints",
             "Are there constraints the model must respect? (size limit, must-not's, security, no internet?)")
    if not re.search(r"\b(if .{2,}|when .{2,}|on error|edge case|fallback|otherwise|what if|handle|robust)\b", lower):
        note("low", "error-handling",
             "What should happen on error / edge case / missing data?")
    if text and text.strip()[-1] not in "?." and len(text) < 6:
        note("high", "too-short",
             "This prompt is almost empty — the model has nothing concrete to act on.")

    vague = [w for w in VAGUE_WORDS if re.search(r"\b" + re.escape(w) + r"\b", lower)]
    if vague:
        checks.append({"severity": "medium", "kind": "vague",
                       "question": f"Ambiguous wording: {'; '.join(sorted(set(vague)))[:120]}. "
                                   "Say exactly what you want."})

    return checks


# ---------------------------------------------------------------------------
# templates & workflow
# ---------------------------------------------------------------------------

# every template: {id, name, keywords, when, skeleton[list[str]]}
TEMPLATES = [
    {"id": "task-code", "name": "Code Task",
     "keywords": ["write", "build", "implement", "create a function", "add feature",
                  "refactor", "fix the bug", "script", "api", "python", "js", "typescript"],
     "when": "You're asking the agent to write, change, or fix code.",
     "skeleton": [
        "Goal: <one sentence, what end-state>",
        "Scope / files: <file or repo, what is already there>",
        "Acceptance: <how you'll know it's done — tests, output, behaviour>",
        "Constraints: <must-not's, versions, style, deps>",
     ]},
    {"id": "task-research", "name": "Research / Explain",
     "keywords": ["research", "explain", "what is", "how does", "compare", "learn about",
                  "summary", "study", "why", "written in plain english"],
     "when": "You want an explanation or a researched answer.",
     "skeleton": [
        "Question: <the specific question, one at a time>",
        "Depth: <short gloss | detailed | academic>",
        "Sources: <web? docs? only your knowledge?>",
        "Format: <paragraphs | bullets | a table>",
     ]},
    {"id": "task-write", "name": "Writing / Email / Post",
     "keywords": ["write an email", "blog", "post", "tweet", "draft", "reply", "copy",
                  "essay", "letter", "subtitle", "caption"],
     "when": "You want the agent to write or rewrite prose.",
     "skeleton": [
        "Audience: <who reads this>",
        "Tone: <casual | professional | direct>",
        "Length: <e.g. 150 words, 3 bullets, 1 line>",
        "What must stay: <facts, names, call to action>",
     ]},
    {"id": "task-debug", "name": "Debug / Diagnose",
     "keywords": ["error", "blows up", "crashes", "doesn't work", "not working", "fails",
                  "exception", "traceback", "why is", "undefined", "returns wrong"],
     "when": "Something is broken and you need it diagnosed.",
     "skeleton": [
        "What you ran: <the exact command / step>",
        "Expected vs actual: <what you got instead>",
        "Evidence: <paste the error message or a minimal repro>",
        "Constraint: <time, web access to look it up? rerun allowed?>",
     ]},
    {"id": "task-plan", "name": "Plan / Design",
     "keywords": ["plan", "outline", "design", "architecture", "roadmap", "strategy",
                  "steps", "break down", "blueprint", "proposal"],
     "when": "You want a structured plan, not an immediate action.",
     "skeleton": [
        "Goal / constraints: <the target and any hard limits>",
        "Deliverable: <a plan doc? a list of steps? a diagram?>",
        "Decision matters: <what choices need a recommendation and why>",
     ]},
    {"id": "task-analyze", "name": "Analyse / Review",
     "keywords": ["analy[sz]e", "review", "assess", "audit", "critique", "evaluate",
                  "score", "compare these", "risk", "check if"],
     "when": "You want the agent to evaluate something.",
     "skeleton": [
        "Subject: <what to evaluate and where>",
        "Criteria: <what 'good' looks like>",
        "Output: <verdict + reasons? a scored list?>",
     ]},
]


def match_template(text: str) -> dict:
    """Classify the prompt against the template library. Returns the closest
    template, or {id:None} when nothing matches."""
    lower = text.lower()
    best, bestscore = None, 0
    for t in TEMPLATES:
        score = sum(1 for k in t["keywords"] if re.search(k, lower))
        if score > bestscore:
            best, bestscore = t, score
    if best and bestscore >= 1:
        return {**best, "matched_score": bestscore}
    return {"id": None, "name": "General", "when": "",
            "skeleton": ["Goal", "Input", "Acceptance / output", "Constraints"],
            "matched_score": 0}


def workflow_suggestions(text: str) -> list[str]:
    """Short workflow tips derived from what's missing."""
    tips = []
    lower = text.lower()
    if re.search(r"\b(then|next)\b", lower):
        tips.append("You describe several steps — tell the agent to do ONE thing per "
                    "message, or accept them as a validated plan before executing.")
    if len(re.findall(r"[?.!]", text)) < 2 and len(text) > 60:
        tips.append("Add a question or an explicit instruction to turn a wall of text into an actionable ask.")
    if re.search(r"\b(details|exactly)\b", lower) or len(text) > 400:
        tips.append("Long prompt: paste real input files/URLs instead of paraphrasing them — "
                    "you save tokens and lose no information.")
    if "plz" in lower or "pls" in lower:
        tips.append("'plz'/'pls' cost tokens and add nothing. Delete them.")
    if len(text.split()) < 12:
        tips.append("Very short prompt: the model guesses intent. Add an acceptance criterion "
                    "('done when…') to stop it over-refining.")
    if not tips:
        tips.append("Looks ready to send — the biggest token saver is already working: no rewrite loop.")
    return tips


# ---------------------------------------------------------------------------
# local (deterministic) rebuild
# ---------------------------------------------------------------------------

def rebuild(text: str) -> str:
    """Apply high-confidence fixes + template framing to produce a tighter draft.
    No LLM — pure rules. Return the improved prompt text."""
    out = text
    for wrong, fix in TYPO_MAP.items():
        pat = re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE)
        if "\b" + wrong in " " or True:
            out = pat.sub(fix, out)
    # strip filler phrases
    for p in FILLER_PHRASES:
        out = re.sub(r"\b" + re.escape(p) + r"\b\s*,?\s*", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if not out:
        return text
    # collapse immediate repeats left by typo fixes ("the the" -> "the")
    out = re.sub(r"\b(\w+)\s+\1\b", r"\1", out)
    tpl = match_template(out)
    if tpl["id"]:
        header = f"[BetterPrompt] Matched template: {tpl['name']}\n"
        return header + out
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def score_penalty(issues: list[dict]):
    table = {"high": 20, "medium": 9, "low": 3}
    return sum(table.get(i.get("severity", "low"), 3) for i in issues)


# ---------------------------------------------------------------------------
# main audit entrypoint
# ---------------------------------------------------------------------------

@dataclass
class AuditResult:
    score: int
    grade: str
    text: str
    tokens: dict
    issues: list = field(default_factory=list)
    spelling: list = field(default_factory=list)
    missed_commands: list = field(default_factory=list)
    recommended_template: dict = field(default_factory=dict)
    workflow: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    rebuilded: str = ""

    def to_dict(self):
        return asdict(self)


GRADE = [(90, "A", "Send it — tight and clear"),
         (75, "B", "Good; one or two small wins"),
         (55, "C", "Will work but wastes tokens"),
         (0, "D", "Rewrite before sending")]


def audit(text: str, model: str = DEFAULT_MODEL,
          output_budget: int = 800) -> AuditResult:
    """Run the full deterministic audit. Returns an AuditResult."""
    text = (text or "").strip()
    cost = estimate_cost(text, model, output_budget)

    issues: list[dict] = []
    spelling = spellcheck(text)
    for s in spelling:
        issues.append({"severity": "medium" if s["confidence"] == "high" else "low",
                       "kind": "spelling",
                       "message": f"\"{s['wrong']}\" → \"{s['fix']}\"",
                       "excerpt": s.get("note")})

    issues.extend(flag_waste(text))
    clarity = clarity_checks(text)
    for c in clarity:
        issues.append({"severity": c["severity"], "kind": c["kind"],
                       "message": c["question"], "excerpt": None})

    tpl = match_template(text)
    workflow = workflow_suggestions(text)

    # command-correction: a leading slash command disambiguates
    missed = []
    slashes = re.findall(r"/(\w+)\b", text)
    for s in slashes:
        if s not in HERMES_COMMANDS:
            low = min(HERMES_COMMANDS, key=lambda c: _levenshtein(s, c))
            if _levenshtein(s, low) <= 2:
                missed.append({"detected": "/" + s, "correct": "/" + low})

    raw = 100 - score_penalty(issues)
    if not text:
        raw = 0
    score = max(0, min(100, raw))
    grade, grade_note = next((g, n) for g, n, _ in GRADE if score >= g)

    questions = [c["question"] for c in clarity]
    if tpl["id"] and tpl["matched_score"] and not tpl["when"].startswith("General"):
        pass

    return AuditResult(
        score=score, grade=grade, text=text,
        tokens=cost,
        issues=issues, spelling=spelling, missed_commands=missed,
        recommended_template=tpl, workflow=workflow, questions=questions,
        rebuilded=rebuild(text) if text else "",
    )


# ---------------------------------------------------------------------------
# fine-tune: interview-then-build a targeted project prompt
# ---------------------------------------------------------------------------

# canonical project-context questions, in the order the interview should ask
FINETUNE_QUESTIONS = [
    {"key": "project", "label": "What project / repo is this about? (language · framework · stack)"},
    {"key": "scope", "label": "Which files or area does it concern?"},
    {"key": "goal", "label": "What is the concrete end goal / behaviour you want?"},
    {"key": "output", "label": "What should the result be? (code, plan, config, a doc, …)"},
    {"key": "accept", "label": "How will you know it's done? (a 'done when…' check)"},
    {"key": "constraints", "label": "Any constraints or must-not's? (versions, limits, security, no internet…)"},
    {"key": "extra", "label": "References or details to include? (URLs, non-use cases, context)"},
]

_QLABEL = {q["key"]: q["label"] for q in FINETUNE_QUESTIONS}


def build_finetuned(answers: dict, draft: str = "") -> str:
    """Assemble a targeted project prompt from interview answers (zero tokens).
    Unknown fields are omitted; a pre-existing draft fills the goal when none
    is given."""
    a = {k: (v or "").strip() for k, v in (answers or {}).items()}
    if not a.get("goal") and draft:
        a["goal"] = draft
    lines = ["You have full context for the following task:", ""]
    if a.get("project"):
        lines.append(f"Project: {a['project']}")
    if a.get("scope"):
        lines.append(f"Scope / files: {a['scope']}")
    if a.get("goal"):
        lines.append(f"Goal: {a['goal']}")
    if a.get("output"):
        lines.append(f"Deliverable: {a['output']}")
    if a.get("accept"):
        lines.append(f"Done when: {a['accept']}")
    if a.get("constraints"):
        lines.append(f"Constraints: {a['constraints']}")
    if a.get("extra"):
        lines.append(f"References / context: {a['extra']}")
    if len(lines) == 2:
        return (draft or "").strip()
    return "\n".join(lines)


def finetune_missing(answers: dict) -> list[str]:
    """The interview questions still unanswered, as readable follow-ups."""
    return [_QLABEL[q["key"]] for q in FINETUNE_QUESTIONS
            if not (answers or {}).get(q["key"]) or not str(answers[q["key"]]).strip()]


# ---------------------------------------------------------------------------
# offline editor: no-AI better generation + spell check
# ---------------------------------------------------------------------------

RUN_ON_LIMIT = 40  # words before a sentence is flagged as a run-on

# pre-saved, offline prompt patterns for common intent ("quick prompt generator")
PLAN_SUGGESTIONS = [
    {"title": "Plan it together",
     "prompt": "Let's plan \"{topic}\" together. Start by asking me the 2-3 most "
               "important questions, then propose a step-by-step plan I can "
               "approve before you build."},
    {"title": "Smallest version first",
     "prompt": "We're making \"{topic}\". Propose the smallest playable/useful "
               "version first, list what you would cut for v1, then ask what "
               "to keep."},
    {"title": "Options + recommendation",
     "prompt": "For \"{topic}\": give me 2-3 concrete options, compare them "
               "briefly, and recommend one with a reason."},
    {"title": "Ask me first",
     "prompt": "Before working on \"{topic}\", ask me the questions that would "
               "change the approach the most — then act on my answers."},
]


def suggest_offline(text: str) -> list[dict]:
    """Canned offline suggestions for short/vague prompts. Zero tokens."""
    t = (text or "").strip()
    if not t or len(t.split()) > 16:
        return []
    topic = t.rstrip(".!?").strip()
    return [{"title": s["title"], "prompt": s["prompt"].format(topic=topic)}
            for s in PLAN_SUGGESTIONS]


def _split_runon(s: str) -> list[str]:
    """Best-effort split of a long sentence (near its midpoint at a conjunction)."""
    words = s.split()
    if len(words) <= RUN_ON_LIMIT:
        return [s]
    n = len(words)
    target = n // 2
    cands = [i for i in range(1, n)
             if words[i].lower() in ("and", "but", "then", "so", "however")
             or words[i - 1].endswith((",", ";"))]
    if not cands:
        return [s]
    best = min(cands, key=lambda i: abs(i - target))
    a = " ".join(words[:best]).rstrip(",;").rstrip()
    a = re.sub(r"(?:\s+(?:and|but|then|so|,)\s*)+$", "", a)  # no trailing conjunction
    b = " ".join(words[best:]).lstrip()
    a = (a + ".") if a and not a.endswith((".", "!", "?")) else a
    b = (b[0].upper() + b[1:]) if b and b[0].islower() else b
    return [a, b] if b else [a]


def _should_framework(t: str, missing: list[str]) -> bool:
    """Frame with a spec block only for a single loose paragraph that lacks
    explicit structure and is missing real context."""
    if not missing:
        return False
    if any(marker in t for marker in ("Goal:", "Deliverable:", "Quick spec", "Done when:", "Scope:")):
        return False
    n = len(t.split())
    return 4 <= n <= 220


def offline_edit(text: str) -> dict:
    """Deterministic, offline prompt editor — zero tokens, no model.

    Tightens grammar, fixes spelling + mistyped commands, strips filler,
    collapses redundancy, splits run-ons, and frames the prompt with the
    missing context as an explicit spec block. Returns the improved prompt
    plus a record of what changed and the score before/after.
    """
    changes = {"typos": [], "suspect": [], "filler": [], "runons": 0, "grammar": 0, "structure": False}
    t = (text or "").strip()
    score_before = audit(t if t else " ").score

    if not t:
        return {"improved": "", "changes": changes, "score_before": 0, "score_after": 0,
                "suggestions": []}

    # grammar: leading capital, standalone i
    if t[0].islower():
        t = t[0].upper() + t[1:]
        changes["grammar"] += 1
    t2 = re.sub(r"\bi\b", "I", t)
    if t2 != t:
        changes["grammar"] += 1
    t = t2

    # spelling
    for wrong, fix in TYPO_MAP.items():
        if not fix:
            continue
        pat = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
        if pat.search(t):
            t = pat.sub(fix, t)
            changes["typos"].append(f"{wrong}→{fix}")

    # possible misspellings — digit/letter mixes the dictionary can't catch
    for w in re.findall(r"[A-Za-z0-9']+", t):
        if re.search(r"\d", w) and re.search(r"[a-z]", w) and len(w) <= 12:
            if w not in changes["suspect"]:
                changes["suspect"].append(w)

    # mistyped commands
    for s in set(re.findall(r"/([a-z]+)\b", t, re.I)):
        low = s.lower()
        if low not in HERMES_COMMANDS:
            cand = min(HERMES_COMMANDS, key=lambda c: _levenshtein(low, c))
            if _levenshtein(low, cand) <= 2 and cand != low:
                t = re.sub(rf"/{re.escape(s)}\b", "/" + cand, t, flags=re.I)
                changes["typos"].append(f"/{s}→/{cand}")

    # filler
    for f in FILLER_PHRASES:
        pat = re.compile(rf"\b{re.escape(f)}\b\s*,?\s?", re.I)
        if pat.search(t):
            t = pat.sub(" ", t)
            changes["filler"].append(f)

    # redundancy collapse (please please, the the, and and …)
    nt = re.sub(r"\b(\w+)\s+\1\b", r"\1", t)
    if nt != t:
        changes["grammar"] += 1
        t = nt

    # restore a subject if filler-stripping dropped a leading "I"
    t = re.sub(r"\s{2,}", " ", t).strip()
    if (re.match(r"^(want|wanna|need|need to)\b", t, re.I)
            and not re.match(r"^I\b", t)):
        t = "I " + t[0].lower() + t[1:]
        changes["grammar"] += 1

    # run-ons
    sents = re.split(r"(?<=[.!?])\s+", t)
    rebuilt = []
    for s in sents:
        if len(s.split()) > RUN_ON_LIMIT:
            parts = _split_runon(s)
            rebuilt.extend(parts)
            changes["runons"] += len(parts) - 1
        else:
            rebuilt.append(s)
    t = re.sub(r"\s{2,}", " ", " ".join(rebuilt)).strip()

    # terminal punctuation
    if t and t[-1] not in ".!?":
        t = t + "."
        changes["grammar"] += 1

    # structural framing (offline "better generation")
    missing = [c["kind"] for c in clarity_checks(text)]
    if _should_framework(t, missing):
        pad = "\n" if t else ""
        block = [pad + "Quick spec so one pass is enough:"]
        if "input-context" in missing:
            block.append("  Input/scope: <file, repo, URL, or paste the data>")
        if "output-format" in missing:
            block.append("  Output: <what you want back — JSON, code, plan, a file?>")
        if "constraints" in missing:
            block.append("  Constraints: <must-nots, size limits, versions>")
        if "error-handling" in missing:
            block.append("  On error / edge case: <what to do when input is missing or wrong>")
        if len(block) > 1:
            t = t + "\n".join(block)
            changes["structure"] = True

    return {"improved": t, "changes": changes,
            "score_before": score_before, "score_after": audit(t).score,
            "suggestions": suggest_offline(text)}


def light_clean(text: str) -> str:
    """Light deterministic cleanup for model output: dictionary spelling fixes,
    filler-phrase removal, repeated-word collapse. No restructuring, no framing —
    safe to run over an LLM's improved prompt."""
    t = (text or "").strip()
    for wrong, fix in TYPO_MAP.items():
        if not fix:
            continue
        t = re.sub(rf"\b{re.escape(wrong)}\b", fix, t, flags=re.IGNORECASE)
    for f in FILLER_PHRASES:
        t = re.sub(rf"\b{re.escape(f)}\b\s*,?\s?", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(\w+)\s+\1\b", r"\1", t)
    t = re.sub(r"\s+([.,!?;])", r"\1", t)  # no space before punctuation
    return re.sub(r"\s{2,}", " ", t).strip()
