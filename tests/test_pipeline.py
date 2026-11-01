"""Offline tests: the model is replaced by a scripted fake, so no API key or network is needed."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main  # noqa: E402

FILLER = "Bob sat on the warm mat. " * 80  # ~480 words, short sentences: passes the code checks


def verdict_json(overrides=None, fixes=()):
    scores = {c: 5 for c in main.CRITERIA}
    scores.update(overrides or {})
    return {
        "assessment": {c: {"evidence": "e", "score": s} for c, s in scores.items()},
        "strengths": ["cozy"],
        "fixes": list(fixes),
    }


GOOD = verdict_json()
WEAK = verdict_json({"wind_down": 2}, ["Slow the ending down."])
BRIEF = {"category": "animal_friends", "characters": [{"name": "Alice", "description": "girl"}],
         "setting": "garden", "tone": "warm", "gentle_lesson": "friendship", "must_keep": ["cat named Bob"], "adjustments": ""}
OUTLINE = {"beats": ["a", "b", "c", "d", "e", "f"], "recurring_phrase": "hush now"}


class FakeModel:
    """Routes by prompt text; judge replies come from a queue."""

    def __init__(self, judge_replies):
        self.judge_replies = list(judge_replies)
        self.calls = []

    def __call__(self, prompt, system=None, max_tokens=3000):
        self.calls.append(prompt)
        if "story editor for a children's" in prompt:
            return "```json\n" + json.dumps(BRIEF) + "\n```"
        if "planning a bedtime story" in prompt:
            return json.dumps(OUTLINE)
        if "judging a bedtime story" in prompt:
            return json.dumps(self.judge_replies.pop(0))
        if "Revise this bedtime story" in prompt:
            return f"**Title**\n{FILLER}revised v{sum('Revise this' in c for c in self.calls)}."
        return f"# Title\n{FILLER}first draft."


def revise_prompts(fake):
    return [c for c in fake.calls if "Revise this bedtime story" in c]


def test_extract_json_handles_fences_and_prose():
    assert main.extract_json('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}


def test_clean_strips_markdown():
    assert main.clean("**Title**\n*Whoosh!* it went") == "Title\nWhoosh! it went"


def test_measurement_flags_length_and_long_sentences():
    assert main.measurement_problems("Title\n" + FILLER) == []
    assert any("only" in p for p in main.measurement_problems("Too short."))
    assert any("Sentences average" in p for p in main.measurement_problems("word " * 500 + "."))


def test_passes_first_time_without_revision(monkeypatch):
    fake = FakeModel([GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    result = main.tell_story("Alice and Bob the cat")
    assert result.story.endswith("first draft.")
    assert "*" not in result.story and not result.story.startswith("#")
    assert result.verdict.passed and "accuracy" in result.verdict.scores
    assert not revise_prompts(fake)


def test_revises_when_judge_finds_problems(monkeypatch):
    fake = FakeModel([WEAK, GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    result = main.tell_story("Alice and Bob the cat")
    assert result.story.endswith("revised v1.")
    assert any("Slow the ending down." in c for c in revise_prompts(fake))  # feedback reaches the writer


def test_keeps_best_draft_if_revision_gets_worse(monkeypatch):
    worse = verdict_json({c: 2 for c in main.CRITERIA}, ["x"])
    fake = FakeModel([WEAK, worse, worse])
    monkeypatch.setattr(main, "call_model", fake)
    assert main.tell_story("anything", max_rounds=2).story.endswith("first draft.")


def test_tie_keeps_the_earlier_draft(monkeypatch):
    fake = FakeModel([WEAK, WEAK, WEAK])
    monkeypatch.setattr(main, "call_model", fake)
    assert main.tell_story("anything", max_rounds=2).story.endswith("first draft.")


def test_code_checks_trigger_revision_even_if_judge_is_happy(monkeypatch):
    fake = FakeModel([GOOD, GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    story, _ = main.improve_with_judge(BRIEF, "Title\nToo short.", max_rounds=1)
    assert story.endswith("revised v1.")
    assert "only" in revise_prompts(fake)[0]  # the word-count problem was passed to the reviser


def test_unusable_judge_output_still_returns_story(monkeypatch):
    class Broken(FakeModel):
        def __call__(self, prompt, **kw):
            if "judging a bedtime story" in prompt:
                return "I loved it!"  # not JSON, twice (initial + retry)
            return super().__call__(prompt, **kw)

    monkeypatch.setattr(main, "call_model", Broken([]))
    result = main.tell_story("anything")
    assert result.story and result.verdict is None


def test_garbage_brief_and_outline_fall_back(monkeypatch):
    class Garbage(FakeModel):
        def __call__(self, prompt, **kw):
            if "story editor for a children's" in prompt or "planning a bedtime story" in prompt:
                return "not json"
            return super().__call__(prompt, **kw)

    monkeypatch.setattr(main, "call_model", Garbage([GOOD]))
    result = main.tell_story("a dragon who loves tea")
    assert result.story and "a dragon who loves tea" in result.brief["must_keep"]


def test_user_request_reaches_the_judge(monkeypatch):
    fake = FakeModel([GOOD, GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    second = main.apply_user_feedback(main.tell_story("Alice and Bob the cat"), "add a dragon")
    judge_prompts = [c for c in fake.calls if "judging a bedtime story" in c]
    assert "Reader request: add a dragon" in judge_prompts[-1]
    assert "Reader request: add a dragon" in second.brief["must_keep"]
    assert any("add a dragon" in c for c in revise_prompts(fake))


def test_cut_off_story_is_flagged():
    assert any("mid-sentence" in p for p in main.measurement_problems("Title\n" + FILLER + "Bob spun"))
    assert not any("mid-sentence" in p for p in main.measurement_problems('Title\n' + FILLER + 'Bob said "Hi!"'))


def test_empty_revision_keeps_the_current_draft(monkeypatch):
    monkeypatch.setattr(main, "call_model", lambda *a, **k: "")
    assert main.revise_story(BRIEF, "Title\nthe original story", ["fix"], source="x") == "Title\nthe original story"


def test_spark_is_reproducible_and_reaches_the_outline(monkeypatch):
    import random

    assert main.pick_spark(random.Random(1)) == main.pick_spark(random.Random(1))
    fake = FakeModel([GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    main.tell_story("anything", seed=1)
    outline_prompt = next(c for c in fake.calls if "planning a bedtime story" in c)
    rng = random.Random(1)
    hero = rng.choice(main.prompts.HERO_NAMES)
    assert main.pick_spark(rng) in outline_prompt
    brief_prompt = next(c for c in fake.calls if "story editor for a children's" in c)
    assert hero in brief_prompt


def test_passing_draft_beats_a_higher_scoring_draft_that_fails(monkeypatch):
    fails = verdict_json({"wind_down": 3}, ["x"])  # total 33, but one noticeable weakness
    passes = verdict_json({c: 4 for c in main.CRITERIA if c != "safety_kindness"}, ["y"])  # total 29, clears the bar
    monkeypatch.setattr(main, "call_model", FakeModel([fails, passes]))
    assert main.tell_story("anything", max_rounds=2).story.endswith("revised v1.")


def test_reviser_is_told_the_current_length(monkeypatch):
    fake = FakeModel([WEAK, GOOD])
    monkeypatch.setattr(main, "call_model", fake)
    main.tell_story("anything")
    assert "The current draft is" in revise_prompts(fake)[0]
