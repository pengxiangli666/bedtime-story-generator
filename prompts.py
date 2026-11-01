"""All prompts live here so they are easy to find, read, and tweak.

Design idea ("the wind-down arc"): a bedtime story is not an ordinary story.
It needs a real arc (so it is engaging), but the energy must *fall* toward the end
so the child is sleepy when it finishes. The planner, writer and judge all know
about this, and the judge scores it explicitly.
"""

AUDIENCE = (
    "children aged 5 to 10 at bedtime, read aloud by a parent. "
    "Vocabulary: mostly simple words, with an occasional fun 'stretch' word explained by context. "
    "Sentences: short to medium, with natural rhythm and a little repetition (kids love it)."
)

# ---------------------------------------------------------------------------
# 1. Request analysis: classify + build a "story brief" + safety-soften
# ---------------------------------------------------------------------------
BRIEF_PROMPT = """You are the story editor for a children's bedtime-story service.
Audience: {audience}

Read the child's (or parent's) request and turn it into a compact story brief.
If the request contains anything unsuitable for ages 5-10 (graphic violence, gore, sexual content,
real-world hate, frightening horror), do NOT refuse: keep the harmless heart of the request and
gently reshape it (e.g. a "scary monster" becomes a shy, misunderstood monster). Say what you changed.

Request: \"\"\"{request}\"\"\"

The hero is whoever or whatever the request is about: for "a story about a dragon", the dragon is the main character, so do not add a separate human hero. If the request does not name the hero, call them {hero}. If it does, keep the requested name.

Return ONLY a JSON object with these keys:
{{
  "category": one of ["adventure", "animal_friends", "fantasy_magic", "everyday_life", "science_nature", "silly_humor"],
  "characters": [{{"name": str, "description": str}}],   // include every character the request names
  "setting": str,
  "tone": str,                    // e.g. "warm and gentle", "playful and giggly"
  "gentle_lesson": str,           // a light theme such as kindness or bravery. Never preachy.
  "must_keep": [str],             // concrete details from the request that the story MUST include.
                                  // If the request has a quirk or twist (e.g. "her best friend Bob, who happens
                                  // to be a cat"), add an item saying how to play with it for charm and humor
                                  // (e.g. "Bob is a cat treated as an ordinary best friend, with funny cat habits").
  "adjustments": str              // ONLY if you removed or softened something unsuitable: one short, friendly sentence saying what you
                                  // changed. Otherwise exactly "" (never explain why a request was fine)
}}"""

# ---------------------------------------------------------------------------
# 2. Outline using a story arc with a built-in wind-down
# ---------------------------------------------------------------------------
OUTLINE_PROMPT = """You are a children's author planning a bedtime story.
Audience: {audience}

Story brief (JSON):
{brief}

Category strategy: {strategy}

Creative spark (weave these in naturally; details from the request always win): {spark}
Give any new character a fresh, distinctive name (not the most common storybook names).

Write a short outline with EXACTLY these 6 beats (one or two sentences each):
1. Cozy beginning: meet the characters in a vivid, specific place.
2. The wish or little problem: something the hero wants or needs.
3. The journey: 2-3 playful attempts or discoveries (include one funny or surprising moment).
4. The turning point: the hero uses kindness, cleverness or courage to solve it. A small problem, never real danger.
5. Happy resolution: everyone is safe, friendships are warmer.
6. Wind-down: the world slows, the characters get sleepy and go to bed. Calm images only (moon, blankets, soft sounds).

Use any quirk or twist from the brief as a source of humor and charm in at least two beats.
Also add one line "recurring_phrase": a short, musical phrase that appears 3 times in the story. Make it specific to THIS story's events, not a generic friendship slogan like 'side by side'.
Return ONLY a JSON object: {{"beats": [6 strings], "recurring_phrase": str}}"""

CATEGORY_STRATEGIES = {
    "adventure": "Small-scale quest with a map, a goal and a friendly obstacle. Wonder over peril.",
    "animal_friends": "Give each animal a distinct voice and quirk. Friendship and teamwork drive the plot.",
    "fantasy_magic": "Magic has one simple, consistent rule. Make the wonder concrete (colors, textures, sounds).",
    "everyday_life": "Find the magic in a familiar place (kitchen, school, park). Emotions feel true and small.",
    "science_nature": "Weave in one real, accurate fact through character curiosity. Awe is the hook.",
    "silly_humor": "Escalating silliness, wordplay and sound effects. Keep the ending extra calm for contrast.",
}
DEFAULT_STRATEGY = CATEGORY_STRATEGIES["adventure"]

# Used only if the outline call returns something unparseable, so the pipeline never dies on it.
DEFAULT_OUTLINE = {
    "beats": [
        "Cozy beginning: meet the characters in a vivid, specific place.",
        "The characters discover a small wish or problem.",
        "A playful journey with a funny or surprising moment.",
        "The turning point: kindness or cleverness solves the problem.",
        "Everyone is safe and friendships feel warmer.",
        "Wind-down: the world slows and the hero falls asleep.",
    ],
    "recurring_phrase": "side by side",
}

# A random pick from each list is woven into every outline so stories differ from run to run.
SPARKS = {
    "sensory detail": [
        "the smell of rain on warm stones", "a sound that echoes", "a color that keeps changing",
        "velvet moss underfoot", "frosty, crunchy grass", "a glow that hums softly",
        "the taste of honey on the breeze", "a ticking, tinkling clockwork sound",
    ],
    "side character": [
        "a grumpy but secretly kind hedgehog", "a forgetful old tortoise", "a shy firefly",
        "a very serious snail", "a gossiping family of crows", "a lighthouse keeper who talks in rhymes",
        "a sleepy bear who is always late", "a tiny dragon afraid of its own sneezes",
    ],
    "small twist": [
        "something small turns out to be bigger than it looks", "the scary-looking obstacle is actually lonely",
        "a lost thing was never really lost", "the helper needs help too",
        "an everyday object comes alive for one night", "the answer was there from the very beginning",
    ],
}

# Used only when the request does not name the hero (left alone, the model always picks the same few names).
HERO_NAMES = [
    "Juniper", "Otis", "Marigold", "Fitz", "Wren", "Tobias", "Odette", "Basil",
    "Hazel", "Rafferty", "Clementine", "Ziggy", "Nell", "Barnaby", "Saffron", "Rhys",
]

# ---------------------------------------------------------------------------
# 3. Writer
# ---------------------------------------------------------------------------
WRITER_SYSTEM = (
    "You are a beloved children's bedtime storyteller. You write warm, vivid, read-aloud-friendly "
    "stories with a clear beginning, middle and end. You never include violence beyond mild "
    "make-believe mishaps, nothing frightening that is left unresolved, and no preachy morals."
)

WRITE_PROMPT = """Write a bedtime story for {audience}

Story brief (JSON):
{brief}

Outline to follow (JSON):
{outline}

Requirements:
- Length: 450-650 words (about 4 minutes read aloud).
- Start with a title on its own line, then the story.
- Include every item in "must_keep" and every named character. If the request has a quirk or twist,
  play with it for humor and charm instead of ignoring it.
- Use the recurring phrase 3 times, first early, last in the closing lines.
- Give any new character a fresh, distinctive name (not the most common storybook names).
- Use some dialogue and at least a few sensory details (sound, touch, smell).
- WIND-DOWN: in the last third, sentences get gradually shorter and softer, and the final lines
  are quiet and sleepy. End with the hero falling asleep (a gentle, satisfying last line).
- Show the lesson through what characters do. Do not state a moral.
- Plain text only: no markdown symbols (no *, #, or bold). Write sound effects as plain words, like Whoosh!
- Output ONLY the title and story text. No notes, no headings other than the title."""

REVISE_PROMPT = """Revise this bedtime story for {audience}

Story brief (JSON):
{brief}

Current draft:
\"\"\"
{story}
\"\"\"

Feedback to address (from {source}):
{feedback}

Rules: this is an EDIT, not a rewrite. Fix every point of feedback by changing only the sentences it concerns;
copy every other paragraph word for word. Keep the voice, characters, recurring phrase and best lines.
Do not touch the sleepy wind-down ending (last third) unless the feedback is about it.
The current draft is {words} words. Keep the title line, and keep the result between 450 and 650 words (never over 700): whenever you add something, cut an equal amount of less important description or repetition (never from the wind-down ending).
Plain text only: no markdown symbols (no *, #, or bold).
Output ONLY the revised title and story."""

# ---------------------------------------------------------------------------
# 4. Judge (evidence first, then score: this makes the scores steadier)
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """You are a strict but kind children's-literature editor judging a bedtime story.
Audience: {audience}

Story brief (JSON):
{brief}

Story:
\"\"\"
{story}
\"\"\"

Score each criterion from 1 to 5 using these anchors: 5 = nothing worth improving; 4 = good, only minor polish;
3 = a noticeable weakness; 2 = a major problem; 1 = fails the criterion. Judge only what is actually on the page
and do not lower a score for something the story clearly does. Any must_keep item that starts with
"Reader request:" was asked for by the parent or child, so treat it as required.
- age_fit: vocabulary, sentence length and themes suit ages 5-10; nothing confusing or frightening.
- request_fidelity: includes every character and "must_keep" detail, matches the tone, and plays with any quirk
  or twist in the request instead of ignoring it.
- story_arc: clear beginning, a real (small) problem, a satisfying turning point and resolution.
- engagement: vivid imagery, humor/surprise, distinct characters, good dialogue, read-aloud rhythm.
- wind_down: 5 = the final third clearly gets quieter, sentences shorten, images are calm, and the hero ends asleep;
  3 = calm ending but the pace does not slow; 1 = ends on action or excitement.
- safety_kindness: no scary, violent, or unsuitable content; a gentle lesson shown, not preached.
- accuracy: for science or nature requests, every explanation or demonstration is scientifically correct (simplified is fine, wrong or misleading is not). For every other kind of story, score 5.

For EACH criterion, first write one sentence of evidence that points to a specific passage, THEN give the score.

Give the 3 most valuable fixes (none for a criterion you scored 5). Each fix must be specific and actionable and
quote or point to the exact passage it refers to. If the story is already excellent, return fewer fixes.

Return ONLY a JSON object:
{{
  "assessment": {{
    "age_fit": {{"evidence": str, "score": int}},
    "request_fidelity": {{"evidence": str, "score": int}},
    "story_arc": {{"evidence": str, "score": int}},
    "engagement": {{"evidence": str, "score": int}},
    "wind_down": {{"evidence": str, "score": int}},
    "safety_kindness": {{"evidence": str, "score": int}},
    "accuracy": {{"evidence": str, "score": int}}
  }},
  "strengths": [str],
  "fixes": [str]
}}"""
