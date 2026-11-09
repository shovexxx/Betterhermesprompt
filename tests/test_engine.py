import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine

BAD = ("hey so basically i just want you to fix teh the website please please, "
       "its not working and stuff. you know, i need it to work. also can you "
       "delete the old stuff but keep it. please just make it better and stuff please")

GOOD = ("Refactor src/api.py to use async/await instead of threading. "
        "Scope: only src/api.py and its tests. Acceptance: all tests in "
        "tests/test_api.py pass and no warning about unclosed loops. "
        "Constraints: python 3.12, stdlib only, keep the existing public "
        "function signatures unchanged.")


def test_tokens():
    assert engine.estimate_tokens("hello world") >= 1
    c = engine.estimate_cost("write a poem", model="gpt-4o")
    assert c["input_tokens"] > 0 and c["est_cost_usd"] >= 0


def test_spelling_high_precision():
    issues = engine.spellcheck("fix teh website and recieve the file")
    wrongs = {s["wrong"] for s in issues}
    assert "teh" in wrongs and "recieve" in wrongs


def test_rambling_flagged():
    flags = engine.flag_waste(BAD)
    kinds = [f["kind"] for f in flags]
    assert "filler" in kinds or "contradiction" in kinds


def test_contradiction_detected():
    c = engine._contradiction("delete the old stuff but keep it")
    assert c is not None


def test_clarity_questions():
    checks = engine.clarity_checks("fix the thing")
    assert any(c["kind"] == "vague" for c in checks)


def test_template_match():
    t = engine.match_template("write a python script to fetch a url")
    assert t["id"] == "task-code"


def test_audit_bad_is_punished():
    r = engine.audit(BAD)
    assert r.score < 70, f"bad prompt scored {r.score}"
    assert any(i["kind"] == "contradiction" for i in r.issues)


def test_audit_good_is_praised():
    r = engine.audit(GOOD)
    assert r.score >= 75, f"good prompt scored {r.score}"
    assert r.recommended_template["id"] == "task-code"


def test_rebuild_never_empty():
    r = engine.audit(BAD)
    assert r.rebuilded and len(r.rebuilded) > 0
    assert "teh" not in r.rebuilded.lower()


def test_score_bounds():
    for t in [BAD, GOOD, "", "hi", "x" * 2000]:
        r = engine.audit(t)
        assert 0 <= r.score <= 100


def test_json_serializable():
    import json
    json.dumps(engine.audit(BAD).to_dict())


def test_build_finetuned():
    ans = {"project": "nyctl (python/click)", "goal": "add --schedule",
           "output": "code + tests", "accept": "pytest green", "constraints": "stdlib only"}
    p = engine.build_finetuned(ans, draft="uber goal")
    assert "Project: nyctl" in p and "Done when: pytest green" in p
    assert "References" not in p  # omitted when unanswered
    # draft fills the goal when the goal field is empty
    p2 = engine.build_finetuned({"project": "x"}, draft="do the thing")
    assert "Goal: do the thing" in p2
    assert engine.finetune_missing({"project": "x"})  # returns unanswered follow-ups


def test_offline_edit():
    r = engine.offline_edit(
        "basically i just want you to fix teh website its not working and stuff "
        "please please, and also i need you to make it faster and then deploy it "
        "and then verify and then update the readme and the ci pipeline.")
    assert r["improved"].startswith("I want")
    assert "teh" not in r["improved"].lower()
    assert r["score_after"] >= r["score_before"]
    assert r["changes"]["typos"] and r["changes"]["structure"]
    # no-AI guarantee: deterministic pure function, no model reference
    assert "model" not in r
    # suspect typos (digit/letter mixes) + canned offline suggestions
    r2 = engine.offline_edit("Lets make a game about co3s.")
    assert "co3s" in r2["changes"]["suspect"]
    assert r2["suggestions"] and all("co3s" in s["prompt"] for s in r2["suggestions"])
    assert len(engine.suggest_offline("Lets make a game about chickens.")) == 4
    assert engine.suggest_offline("a long prompt " * 20) == []  # only for short/vague
    # light_clean: deterministic spelling/filler cleanup for model output
    assert "teh" not in engine.light_clean("It teh basically unnecessary, please please fix it and stuff.")
    assert " ." not in engine.light_clean("fix it and stuff.")


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
