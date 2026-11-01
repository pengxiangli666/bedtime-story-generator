"""Bedtime story generator: request -> brief -> outline -> draft -> judge + checks -> revise -> story.

Run:  export ANTHROPIC_API_KEY=...   then   python main.py
See README.md for setup and the block diagram.

What I would build next with two more hours:
1. Persistent "story world": remember a child's name, favorite animals, and past characters across
   sessions so stories can have recurring friends and gentle continuity (a nightly series).
2. A small eval harness: ~20 diverse and adversarial requests, run on every prompt change, tracking
   judge scores, word counts and a real reading-level metric (Flesch-Kincaid; today I only check average
   sentence length), so prompt tweaks are measured instead of eyeballed. Also calibrate the judge against a
   few human-labeled stories and use a second judge (or a different model) to reduce self-preference bias
   and score noise. Add a fact-check pass for science requests: in testing, the judge accepted a
   glitter-in-water demo for 'why is the sky blue' although it shows reflection, not scattering
   (a few drops of milk in water would be accurate).
3. Read-aloud polish: pacing markers and an optional text-to-speech pass with slower speech in the
   wind-down section, plus an interactive mode where the child picks what happens next.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass

import anthropic

import prompts

MODEL = "claude-haiku-5-5"

# Judge thresholds: a draft is "good enough" when every score >= PASS_SCORE
# and safety_kindness is perfect. Otherwise we revise (up to MAX_ROUNDS times).
PASS_SCORE = 4
MAX_ROUNDS = 2
CRITERIA = ["age_fit", "request_fidelity", "story_arc", "engagement", "wind_down", "safety_kindness", "accuracy"]

# Things code can measure better than an LLM, so code checks them (the prompt asks for 450-650 words;
# these limits leave some slack).
WORD_RANGE = (400, 700)
MAX_AVG_SENTENCE_WORDS = 14
PROBLEM_PENALTY = 3  # each failed code check costs this many points when ranking drafts


def _quiet(*_args) -> None:
    """Default logger: does nothing."""


# ---------------------------------------------------------------------------
# Model access
# ---------------------------------------------------------------------------
_client: anthropic.Anthropic | None = None


def call_model(prompt: str, system: str | None = None, max_tokens: int = 8000) -> str:
    """Single place that talks to the API. The key is read from ANTHROPIC_API_KEY (never hard-coded)."""
    global _client
    if _client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=<your key>")
        _client = anthropic.Anthropic()
    kwargs = {"system": system} if system else {}
    resp = _client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    if resp.stop_reason == "max_tokens":
        print("[warning] a model reply hit the token limit and may be cut off", file=sys.stderr)
    return "".join(block.text for block in resp.content if block.type == "text").strip()


def call_json(prompt: str, retries: int = 1) -> dict:
    """Call the model and parse a JSON object from the reply, retrying once on malformed output."""
    last_err: Exception | None = None
    for _ in range(retries + 1):
        text = call_model(prompt)
        try:
            return extract_json(text)
        except ValueError as err:
            last_err = err
    raise ValueError(f"Model did not return valid JSON: {last_err}")


def extract_json(text: str) -> dict:
    """Pull the first {...} object out of a reply (tolerates ```json fences or stray prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as err:
        raise ValueError(str(err)) from err
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    return data


# ---------------------------------------------------------------------------
# Deterministic helpers (no LLM)
# ---------------------------------------------------------------------------
def clean(text: str) -> str:
    """Strip markdown the model sometimes adds (**bold**, *sound effects*, # headings): output is read in a terminal."""
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text.replace("*", "").strip()


def measure(story: str) -> dict:
    words = re.findall(r"[\w']+", story)
    sentences = [s for s in re.split(r"[.!?]+", story) if re.search(r"\w", s)]
    return {
        "words": len(words),
        "avg_sentence_words": round(len(words) / max(len(sentences), 1), 1),
    }


def measurement_problems(story: str) -> list[str]:
    """Objective problems the LLM judge is unreliable at spotting, phrased as fixes for the reviser."""
    m = measure(story)
    low, high = WORD_RANGE
    problems = []
    if not re.search(r"[.!?][\"'\u201d\u2019)]*$", story.strip()):
        problems.append("The story ends mid-sentence. Finish the scene and end with the hero falling asleep.")
    if m["words"] < low:
        problems.append(
            f"The story is only {m['words']} words. Expand it to about 450-650 words by adding vivid detail "
            "and playful moments in the middle (not by lengthening the ending)."
        )
    elif m["words"] > high:
        problems.append(f"The story is {m['words']} words. Trim it to about 450-650 words by tightening the middle.")
    if m["avg_sentence_words"] > MAX_AVG_SENTENCE_WORDS:
        problems.append(
            f"Sentences average {m['avg_sentence_words']} words. Shorten the longest ones (aim for under 12 on "
            "average) so a young child can follow them read aloud."
        )
    return problems


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    scores: dict[str, int]
    evidence: dict[str, str]
    strengths: list[str]
    fixes: list[str]

    @property
    def total(self) -> int:
        return sum(self.scores.values())

    @property
    def passed(self) -> bool:
        return all(s >= PASS_SCORE for s in self.scores.values()) and self.scores["safety_kindness"] == 5


@dataclass
class Result:
    story: str
    verdict: Verdict | None
    brief: dict


def default_brief(request: str) -> dict:
    """Minimal brief used if the brief call returns something unparseable."""
    return {
        "category": "adventure",
        "characters": [],
        "setting": "",
        "tone": "warm and gentle",
        "gentle_lesson": "kindness",
        "must_keep": [request],
        "adjustments": "",
    }


def make_brief(request: str, hero: str) -> dict:
    """Classify the request, extract characters/details, and softly fix unsuitable content."""
    try:
        brief = call_json(prompts.BRIEF_PROMPT.format(audience=prompts.AUDIENCE, request=request, hero=hero))
    except ValueError:
        return default_brief(request)
    brief.setdefault("category", "adventure")
    brief.setdefault("must_keep", [])
    brief.setdefault("adjustments", "")
    return brief


def pick_spark(rng: random.Random) -> str:
    """A small random 'creative spark' (sensory detail + side character + twist) so stories differ between runs."""
    return "; ".join(f"{kind}: {rng.choice(options)}" for kind, options in prompts.SPARKS.items())


def make_outline(brief: dict, spark: str) -> dict:
    strategy = prompts.CATEGORY_STRATEGIES.get(brief["category"], prompts.DEFAULT_STRATEGY)
    try:
        return call_json(
            prompts.OUTLINE_PROMPT.format(audience=prompts.AUDIENCE, brief=json.dumps(brief), strategy=strategy, spark=spark)
        )
    except ValueError:
        return prompts.DEFAULT_OUTLINE


def write_story(brief: dict, outline: dict) -> str:
    prompt = prompts.WRITE_PROMPT.format(
        audience=prompts.AUDIENCE, brief=json.dumps(brief), outline=json.dumps(outline)
    )
    return clean(call_model(prompt, system=prompts.WRITER_SYSTEM))


def revise_story(brief: dict, story: str, feedback: list[str], source: str) -> str:
    prompt = prompts.REVISE_PROMPT.format(
        audience=prompts.AUDIENCE,
        brief=json.dumps(brief),
        story=story,
        source=source,
        words=measure(story)["words"],
        feedback="\n".join(f"- {f}" for f in feedback),
    )
    for _ in range(2):
        revised = clean(call_model(prompt, system=prompts.WRITER_SYSTEM))
        if len(revised.split()) >= 50:  # an empty or tiny reply is a failure, not a revision
            return revised
    return story


def judge_story(brief: dict, story: str) -> Verdict | None:
    """Score the story against the rubric. Returns None if the judge's output is unusable."""
    try:
        data = call_json(prompts.JUDGE_PROMPT.format(audience=prompts.AUDIENCE, brief=json.dumps(brief), story=story))
        assessment = data["assessment"]
        scores = {c: min(5, max(1, int(assessment[c]["score"]))) for c in CRITERIA}
        evidence = {c: str(assessment[c].get("evidence", "")) for c in CRITERIA}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return Verdict(
        scores=scores,
        evidence=evidence,
        strengths=[str(s) for s in data.get("strengths", [])],
        fixes=[str(f) for f in data.get("fixes", [])],
    )


def format_scores(verdict: Verdict | None) -> str:
    if verdict is None:
        return "judge output unusable"
    parts = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
    return f"{parts} (total {verdict.total}/{5 * len(CRITERIA)}, {'PASS' if verdict.passed else 'needs work'})"


def improve_with_judge(brief: dict, draft: str, max_rounds: int = MAX_ROUNDS, log=_quiet) -> tuple[str, Verdict | None]:
    """Judge + code checks -> revise loop.

    Keeps the best-ranked draft (a later draft must be strictly better to replace an earlier one),
    so a bad revision can never make the result worse.
    """
    current = draft
    best: tuple[tuple[bool, int], str, Verdict | None, int] | None = None  # (rank, story, verdict, round)
    for round_no in range(max_rounds + 1):
        verdict = judge_story(brief, current)
        problems = measurement_problems(current)
        m = measure(current)
        log(f"[judge] round {round_no}: {format_scores(verdict)}")
        log(f"[check] words={m['words']} avg_sentence_words={m['avg_sentence_words']}" + (f" PROBLEMS={len(problems)}" if problems else ""))
        for fix in (verdict.fixes if verdict else []) + problems:
            log(f"        - {fix}")

        # A draft that clears the whole bar beats one that does not, whatever the totals; then the higher total wins.
        clears_bar = verdict is not None and verdict.passed and not problems
        rank = (clears_bar, (verdict.total if verdict else 0) - PROBLEM_PENALTY * len(problems))
        if best is None or rank > best[0]:
            best = (rank, current, verdict, round_no)

        fixes = (verdict.fixes if verdict else []) + problems
        satisfied = (verdict is None or verdict.passed) and not problems
        if satisfied or not fixes or round_no == max_rounds:
            break
        log(f"[revise] applying {len(fixes)} fixes")
        current = revise_story(brief, current, fixes, source="the editor")

    assert best is not None
    log(f"[final] shipped the draft from round {best[3]}")
    return best[1], best[2]


def tell_story(request: str, max_rounds: int = MAX_ROUNDS, log=_quiet, seed: int | None = None) -> Result:
    """Full pipeline for one request."""
    rng = random.Random(seed)
    hero = rng.choice(prompts.HERO_NAMES)
    spark = pick_spark(rng)
    brief = make_brief(request, hero)
    log(f"[brief] category={brief['category']}" + (f" | adjusted: {brief['adjustments']}" if brief["adjustments"] else ""))
    log(f"[spark] {spark} | hero name if unnamed: {hero}")
    outline = make_outline(brief, spark)
    log("[outline] ready")
    draft = write_story(brief, outline)
    log("[write] first draft done")
    story, verdict = improve_with_judge(brief, draft, max_rounds, log)
    return Result(story=story, verdict=verdict, brief=brief)


def apply_user_feedback(result: Result, feedback: str, log=_quiet) -> Result:
    """Revise per the user's own request, then judge again so quality and safety stay enforced."""
    # Add the request to the brief so the judge treats it as required instead of penalising it.
    brief = {**result.brief, "must_keep": [*result.brief.get("must_keep", []), f"Reader request: {feedback}"]}
    revised = revise_story(brief, result.story, [feedback], source="the parent/child")
    story, verdict = improve_with_judge(brief, revised, max_rounds=1, log=log)
    return Result(story=story, verdict=verdict, brief=brief)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
example_requests = "A story about a girl named Alice and her best friend Bob, who happens to be a cat."


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a bedtime story for ages 5-10.")
    parser.add_argument("request", nargs="?", help="what the story should be about (prompted if omitted)")
    parser.add_argument("-r", "--rounds", type=int, default=MAX_ROUNDS, help="max judge->revise rounds")
    parser.add_argument("-v", "--verbose", action="store_true", help="show brief, judge scores, fixes and checks")
    parser.add_argument("--no-feedback", action="store_true", help="skip the follow-up 'any changes?' loop")
    parser.add_argument("--seed", type=int, help="make the random creative spark reproducible")
    args = parser.parse_args()

    request = args.request or input(f"What kind of story do you want to hear?\n(e.g. {example_requests})\n> ").strip()
    if not request:
        sys.exit("Please describe a story.")

    log = (lambda msg: print(msg, file=sys.stderr)) if args.verbose else _quiet
    try:
        print("\nOnce upon a time... (writing your story)\n", file=sys.stderr)
        result = tell_story(request, max_rounds=args.rounds, log=log, seed=args.seed)
        if result.brief.get("adjustments"):
            print(f"(Note: I made the story a bit gentler: {result.brief['adjustments']})\n")
        print(result.story)

        while not args.no_feedback:
            try:
                feedback = input("\nWant any changes? (e.g. 'make it funnier', 'add a dragon') or press Enter to finish: ").strip()
            except EOFError:
                break
            if not feedback:
                break
            result = apply_user_feedback(result, feedback, log=log)
            print("\n" + result.story)
    except anthropic.AuthenticationError:
        sys.exit("The API rejected your key. Check ANTHROPIC_API_KEY.")
    except anthropic.APIError as err:
        sys.exit(f"The Anthropic API returned an error: {err}")
    print("\nSweet dreams!")


if __name__ == "__main__":
    main()
