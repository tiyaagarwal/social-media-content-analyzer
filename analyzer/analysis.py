"""
Social media content analysis engine.

Two modes:

  1. AI mode  - used automatically when ANTHROPIC_API_KEY is set. The
     extracted text is sent to the Claude API with a prompt that asks for
     the same structured fields the heuristic engine produces, so the
     frontend does not need to know which mode ran.

  2. Heuristic mode (default/fallback) - a deterministic, rule-based
     engine that actually reads the given text: it counts sentences and
     syllables for readability, scans for hooks/CTAs/hashtags/emoji that
     are already present, extracts real keywords by frequency, and uses
     all of that to build the score, strengths, gaps, and rewrite. It is
     not a static canned response - two different inputs produce
     different output.

Both modes return a plain dict with the same keys (see `ANALYSIS_KEYS`).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

import requests

ANALYSIS_KEYS = [
    "engagement_score",
    "tone",
    "readability",
    "strengths",
    "improvements",
    "rewrite",
    "hooks",
    "cta",
    "hashtags",
    "summary",
    "source",
]

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-5")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "to", "of",
    "in", "on", "for", "with", "at", "by", "from", "up", "about", "into",
    "over", "after", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "we", "you",
    "your", "our", "i", "my", "me", "us", "they", "them", "their", "he",
    "she", "his", "her", "not", "no", "do", "does", "did", "will",
    "would", "can", "could", "should", "have", "has", "had", "just",
    "than", "too", "very", "there", "here", "what", "when", "how",
    "all", "out", "get", "got", "one", "more", "some", "any", "who",
    "which", "am", "was", "im", "know", "really", "going", "even",
    "make", "makes", "made", "way", "ways", "back", "still", "much",
    "many", "want", "wanted", "need", "needs", "think", "thing",
    "things", "available", "using", "used", "use", "launched",
    "launch", "released", "release", "comes", "come", "tried",
    "try", "trying", "went", "goes", "found", "find", "looking",
    "look", "looked", "feel", "felt", "seen", "saw", "said", "says",
    "here", "your", "our", "highly",
}

POSITIVE_WORDS = {
    "amazing", "awesome", "great", "love", "excited", "excellent",
    "happy", "best", "wonderful", "incredible", "fantastic", "win",
    "proud", "thrilled", "grateful", "success", "breakthrough", "new",
    "free", "easy", "fun", "beautiful", "powerful", "boost", "growth",
    "improve", "improved", "launch", "launching", "innovative", "top",
}

NEGATIVE_WORDS = {
    "bad", "worst", "fail", "failed", "problem", "issue", "hate",
    "sad", "angry", "sorry", "unfortunately", "delay", "delayed",
    "cancel", "cancelled", "broken", "difficult", "hard", "struggle",
    "concern", "concerned", "warning", "risk", "loss",
}

CTA_PATTERNS = [
    r"\bcomments?\b", r"\bshares?\b", r"\bclick\w*\b", r"\bsign ?up\b",
    r"\blearn more\b", r"\bdm me\b", r"\bfollow\w*\b", r"\bsubscribe\w*\b",
    r"\bshop now\b", r"\bswipe up\b", r"\blink in bio\b", r"\bsave (this|it)\b",
    r"\btag (a friend|someone)\b", r"\bjoin\w*\b", r"\bregister\b", r"\bdownload\b",
    r"\bvisit\b", r"\bcheck (it |this )?out\b", r"\btry (it|this)\b", r"\bbook now\b",
    r"\border now\b", r"\blet me know\b", r"\bdrop (a|it)\b", r"\bmessage me\b",
]

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)


class AnalysisError(Exception):
    pass


# --------------------------------------------------------------------------
# Shared text utilities
# --------------------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def _count_syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def _flesch_reading_ease(words: list[str], sentences: list[str]) -> float:
    if not words or not sentences:
        return 0.0
    syllables = sum(_count_syllables(w) for w in words)
    score = (
        206.835
        - 1.015 * (len(words) / len(sentences))
        - 84.6 * (syllables / len(words))
    )
    return round(max(0.0, min(100.0, score)), 1)


def _readability_label(score: float) -> str:
    if score >= 80:
        return "Very easy to read"
    if score >= 60:
        return "Easy to read"
    if score >= 50:
        return "Fairly readable"
    if score >= 30:
        return "Somewhat difficult"
    return "Difficult to read"


def _extract_keywords(words: list[str], top_n: int = 8) -> list[str]:
    freq = Counter(
        w.lower() for w in words
        if len(w) > 3 and w.lower() not in STOPWORDS
    )
    # Repeated words are more likely to be the real topic than a one-off
    # word that just happens to appear early in the text.
    repeated = [w for w, c in freq.most_common() if c > 1]
    singles = [w for w, c in freq.most_common() if c == 1]
    ordered = repeated + singles
    return ordered[:top_n]


def _existing_hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text)


def _has_cta(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in CTA_PATTERNS)


def _emoji_count(text: str) -> int:
    return len("".join(EMOJI_PATTERN.findall(text)))


def _detect_tone(text: str, words: list[str]) -> str:
    lowered = text.lower()
    exclaims = text.count("!")
    questions = text.count("?")
    pos = sum(1 for w in words if w.lower() in POSITIVE_WORDS)
    neg = sum(1 for w in words if w.lower() in NEGATIVE_WORDS)
    has_numbers = bool(re.search(r"\d", text))
    cta = _has_cta(text)
    emojis = _emoji_count(text)

    if cta and (pos > neg):
        return "Promotional & upbeat"
    if questions >= 2 or (questions >= 1 and len(words) < 60):
        return "Conversational & inquisitive"
    if exclaims >= 2 and pos >= 1:
        return "Energetic & enthusiastic"
    if neg > pos and neg > 0:
        return "Candid / addressing a problem"
    if has_numbers and pos <= 1 and neg <= 1 and exclaims == 0:
        return "Informative & factual"
    if pos > neg:
        return "Positive & encouraging"
    if emojis > 2:
        return "Casual & playful"
    return "Neutral / matter-of-fact"


# --------------------------------------------------------------------------
# Heuristic engine
# --------------------------------------------------------------------------

def _hook_strength(first_sentence: str) -> tuple[int, str]:
    """Score the opening line's ability to stop the scroll (0-25)."""
    if not first_sentence:
        return 0, "no opening line"

    s = first_sentence.strip()
    score = 8  # baseline for having any opener at all
    reasons = []

    if s.endswith("?"):
        score += 6
        reasons.append("asks a question")
    if re.match(r"^\d", s) or re.search(r"\b\d+%|\b\d+x\b", s):
        score += 6
        reasons.append("leads with a number/stat")
    if re.match(r"^(stop|imagine|here'?s|why|how|the truth|nobody|what if)", s, re.I):
        score += 5
        reasons.append("uses a pattern-interrupt opener")
    if len(s.split()) <= 12:
        score += 3
        reasons.append("short and punchy")
    else:
        reasons.append("a bit long for a scroll-stopping opener")

    score = min(score, 25)
    reason = ", ".join(reasons) if reasons else "a plain, declarative opener"
    return score, reason


def _length_score(word_count: int) -> tuple[int, str]:
    if word_count == 0:
        return 0, "no content"
    if 25 <= word_count <= 150:
        return 15, "in the sweet spot for a social caption"
    if 10 <= word_count < 25:
        return 10, "on the short side - fine for a punchy post, thin for a story"
    if 150 < word_count <= 300:
        return 9, "on the longer side - consider trimming for scannability"
    if word_count < 10:
        return 4, "very short - may not give readers enough to engage with"
    return 5, "quite long for most feeds - readers may drop off"


def run_heuristic_analysis(text: str, tone_preference: str | None = None) -> dict:
    text = text.strip()
    if not text:
        raise AnalysisError("There is no text to analyze.")

    words = _words(text)
    sentences = _sentences(text)
    word_count = len(words)

    flesch = _flesch_reading_ease(words, sentences)
    readability_label = _readability_label(flesch)

    tone = _detect_tone(text, words)
    keywords = _extract_keywords(words)
    existing_hashtags = _existing_hashtags(text)
    has_cta = _has_cta(text)
    emoji_count = _emoji_count(text)

    hook_score, hook_reason = _hook_strength(sentences[0] if sentences else "")
    length_pts, length_reason = _length_score(word_count)

    readability_pts = round(min(20, max(0, (flesch / 100) * 20)))
    cta_pts = 15 if has_cta else 0
    hashtag_pts = 10 if 1 <= len(existing_hashtags) <= 8 else (4 if existing_hashtags else 0)
    emoji_pts = 8 if 1 <= emoji_count <= 6 else (3 if emoji_count > 6 else 0)
    paragraph_pts = 5 if "\n" in text else 2

    engagement_score = round(
        hook_score + length_pts + readability_pts + cta_pts
        + hashtag_pts + emoji_pts + paragraph_pts
    )
    engagement_score = max(1, min(100, engagement_score))

    # ---- strengths (only include what's actually true) ----
    strengths = []
    if hook_score >= 15:
        strengths.append(f"Strong opening line - it {hook_reason}.")
    if has_cta:
        strengths.append("Includes a clear call-to-action, giving readers a next step.")
    if existing_hashtags:
        strengths.append(f"Already uses {len(existing_hashtags)} hashtag(s) for discoverability.")
    if 25 <= word_count <= 150:
        strengths.append("Length is well-matched to how people scroll social feeds.")
    if flesch >= 60:
        strengths.append(f"Easy to read ({readability_label.lower()}, Flesch {flesch}) - low friction for skimmers.")
    if emoji_count >= 1:
        strengths.append("Uses emoji, which can draw the eye in a crowded feed.")
    if not strengths:
        strengths.append("The core message comes through clearly, giving you a solid draft to build on.")

    # ---- improvements (only include what's actually missing/weak) ----
    improvements = []
    if hook_score < 15:
        improvements.append(f"The opening line is {hook_reason} - lead with a question, a number, or a bold claim to stop the scroll.")
    if not has_cta:
        improvements.append("There's no call-to-action - tell readers exactly what to do next (comment, save, click, share).")
    if not existing_hashtags:
        improvements.append("No hashtags yet - a few targeted tags widen discovery beyond your existing followers.")
    elif len(existing_hashtags) > 8:
        improvements.append("A lot of hashtags are in use - trimming to 3-8 focused tags usually reads less spammy.")
    if word_count > 300:
        improvements.append("This runs long for a social caption - consider trimming or splitting into a carousel/thread.")
    if word_count < 10:
        improvements.append("This is quite short - adding one concrete detail or takeaway would give readers more to react to.")
    if flesch < 50:
        improvements.append(f"Sentences are dense (Flesch {flesch}) - shorter sentences and simpler words will read faster on mobile.")
    if emoji_count == 0:
        improvements.append("No emoji used - one or two relevant emoji can add personality and break up text visually.")
    if "\n" not in text and word_count > 40:
        improvements.append("This is one solid block of text - line breaks between ideas make it easier to skim.")
    if not improvements:
        improvements.append("This is already solid - test it against a slightly shorter variant to see what your audience prefers.")

    hashtags = existing_hashtags[:8] if existing_hashtags else [f"#{kw}" for kw in keywords[:5]]
    hooks = _generate_hooks(sentences[0] if sentences else "", keywords, text)
    ctas = _generate_ctas(tone, has_cta)
    rewrite = _generate_rewrite(text, keywords, has_cta, emoji_count, hook_score, tone_preference)

    summary = (
        f"{word_count}-word post, {tone.lower()} in tone, currently scoring "
        f"{engagement_score}/100 on engagement fundamentals."
    )

    return {
        "engagement_score": engagement_score,
        "tone": tone,
        "readability": {
            "flesch_reading_ease": flesch,
            "label": readability_label,
            "avg_sentence_length": round(word_count / len(sentences), 1) if sentences else 0,
            "sentence_count": len(sentences),
            "word_count": word_count,
        },
        "strengths": strengths,
        "improvements": improvements,
        "rewrite": rewrite,
        "hooks": hooks,
        "cta": ctas,
        "hashtags": hashtags,
        "summary": summary,
        "source": "heuristic",
    }


def _generate_hooks(first_sentence: str, keywords: list[str], text: str) -> list[str]:
    topic = keywords[0] if keywords else "this"
    topic2 = keywords[1] if len(keywords) > 1 else topic
    stat_match = re.search(r"\b\d+%|\b\d+x\b|\b\d{2,}\b", text)
    stat = stat_match.group(0) if stat_match else None

    hooks = [
        f"Here's what most people get wrong about {topic}.",
        f"Stop scrolling if {topic} and {topic2} matter to you.",
    ]
    if stat:
        hooks.append(f"{stat} - here's what that actually means for {topic}.")
    else:
        hooks.append(f"3 things I wish I knew about {topic} sooner.")
    return hooks


def _generate_ctas(tone: str, has_cta: bool) -> list[str]:
    base = []
    if "Promotional" in tone:
        base = [
            "Tap the link in bio to get started.",
            "Shop now - link in bio.",
            "DM us to claim this before it's gone.",
        ]
    elif "Conversational" in tone or "inquisitive" in tone:
        base = [
            "Tell me in the comments - do you agree?",
            "Drop a \U0001F447 if this is you too.",
            "What would you add to this list?",
        ]
    elif "Informative" in tone:
        base = [
            "Save this post so you don't lose it later.",
            "Share this with someone who needs to see it.",
            "Follow for more breakdowns like this.",
        ]
    else:
        base = [
            "Let me know your thoughts in the comments.",
            "Save this for later.",
            "Share this if it resonated with you.",
        ]
    if has_cta:
        base.insert(0, "Your current CTA works - consider A/B testing it against:")
    return base[:3]


def _generate_rewrite(
    text: str, keywords: list[str], has_cta: bool, emoji_count: int, hook_score: int, tone_preference: str | None = None
) -> str:
    """Build an improved version without destructively reflowing the
    original structure (so numbered lists / line breaks the author already
    chose are preserved). A weak opener is replaced; a strong one is kept."""
    body = text.strip()
    topic = keywords[0] if keywords else None

    lines: list[str] = []

    if tone_preference == "professional":
        if hook_score < 15 and topic:
            lines.append(f"Regarding the growth and impact of {topic}:")
            lines.append("")
        lines.append(body)
        if not has_cta:
            lines.append("")
            lines.append("For further insights and discussion, feel free to connect or share your perspective below.")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw.capitalize()}" for kw in keywords[:4]))
            
    elif tone_preference == "witty":
        if hook_score < 15 and topic:
            lines.append(f"Let's be honest: most advice about {topic} is pretty boring. Here is the actual reality:")
            lines.append("")
        lines.append(body)
        if not has_cta:
            lines.append("")
            lines.append("Drop a comment if you've been here, or save this before you forget it.")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw}" for kw in keywords[:5]))
            
    elif tone_preference == "educational":
        if hook_score < 15 and topic:
            lines.append(f"Understanding {topic} is key to navigating this space. Here is what you need to know:")
            lines.append("")
        lines.append(body)
        if not has_cta:
            lines.append("")
            lines.append("Save this post for reference next time you're working on this.")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw}" for kw in keywords[:5]))
            
    elif tone_preference == "hype":
        if hook_score < 15 and topic:
            lines.append(f"🚨 Huge shift happening in {topic} right now! Here is the breakdown:")
            lines.append("")
        lines.append(body)
        lines.append("")
        lines.append("✨ Check the link in bio to get started right now! 🚀")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw.upper()}" for kw in keywords[:5]))
            
    elif tone_preference == "short":
        sentences = _sentences(text)
        short_body = sentences[0] if sentences else body
        if len(sentences) > 1:
            short_body += " " + sentences[1]
        lines.append(short_body)
        if not has_cta:
            lines.append("")
            lines.append("Agree or disagree? Let me know.")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw}" for kw in keywords[:3]))
            
    else:
        if hook_score < 15 and topic:
            lines.append(f"Here's what most people get wrong about {topic}:")
            lines.append("")
        lines.append(body)
        if emoji_count == 0:
            lines.append("")
            lines.append("\u2728")
        if not has_cta:
            lines.append("")
            lines.append("Save this if it was useful, and share it with someone who needs it.")
        if keywords and not re.search(r"#\w+", text):
            lines.append("")
            lines.append(" ".join(f"#{kw}" for kw in keywords[:5]))

    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# AI-backed engine (used when ANTHROPIC_API_KEY is configured)
# --------------------------------------------------------------------------

_AI_SYSTEM_PROMPT = """You are a social media content strategist. You will be given the raw \
text of a social media post (possibly extracted via OCR, so tolerate minor artifacts). \
Analyze it and respond with ONLY a single JSON object (no prose, no markdown fences) \
with exactly these keys:

{
  "engagement_score": <integer 0-100>,
  "tone": <short string, e.g. "Energetic & enthusiastic">,
  "readability": {"label": <short string>, "notes": <short string>},
  "strengths": [<2-5 short strings, specific to this text>],
  "improvements": [<2-5 short strings, specific to this text>],
  "rewrite": <an improved version of the post as a single string, using \\n for line breaks>,
  "hooks": [<3 alternative opening lines>],
  "cta": [<2-3 suggested calls-to-action>],
  "hashtags": [<3-8 relevant hashtags, each starting with #>],
  "summary": <one sentence summary of the post's current state>
}

Be specific to the actual content given - do not return generic advice."""


def run_ai_analysis(text: str, api_key: str, tone_preference: str | None = None) -> dict:
    model = os.environ.get("ANALYSIS_MODEL", "").strip() or DEFAULT_MODEL
    # Normalize model override if it was meant for Gemini but we fell back or vice versa
    if "claude" not in model.lower() and model == DEFAULT_MODEL:
        model = "claude-3-5-sonnet-20241022"
    elif not model or "claude" not in model.lower():
        model = "claude-3-5-sonnet-20241022"

    sys_prompt = _AI_SYSTEM_PROMPT
    if tone_preference:
        sys_prompt += (
            f"\n\nCRITICAL: The user has requested the tone of the rewrite to be '{tone_preference}'. "
            f"Tailor the rewritten draft ('rewrite' key), alternative hooks ('hooks' key), "
            f"and suggestions to match this requested tone."
        )

    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": sys_prompt,
        "messages": [{"role": "user", "content": text[:8000]}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(ANTHROPIC_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AnalysisError(f"AI analysis request failed: {exc}") from exc

    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(text_blocks).strip()
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"AI response was not valid JSON: {exc}") from exc

    parsed["source"] = "ai"
    return parsed


def run_gemini_analysis(text: str, api_key: str, tone_preference: str | None = None) -> dict:
    model = os.environ.get("ANALYSIS_MODEL", "").strip()
    if not model or "gemini" not in model.lower():
        model = DEFAULT_GEMINI_MODEL
    url = GEMINI_API_URL.format(model=model) + f"?key={api_key}"

    sys_instruction = (
        "You are an expert social media content strategist. You will be given the raw text "
        "of a social media post (possibly extracted via OCR, so tolerate minor artifacts). "
        "Analyze it and return a structured JSON response matching the schema. "
    )
    if tone_preference:
        sys_instruction += (
            f"CRITICAL: The user has requested the tone of the rewrite to be '{tone_preference}'. "
            f"Tailor the rewritten draft ('rewrite' key), alternative hooks ('hooks' key), "
            f"and suggestions to match this requested tone."
        )

    schema = {
        "type": "OBJECT",
        "properties": {
            "engagement_score": {
                "type": "INTEGER",
                "description": "An overall engagement quality score from 1 to 100."
            },
            "tone": {
                "type": "STRING",
                "description": "The detected tone of the original post."
            },
            "readability": {
                "type": "OBJECT",
                "properties": {
                    "label": {
                        "type": "STRING",
                        "description": "Readability category: e.g. Easy to read, Difficult to read."
                    },
                    "notes": {
                        "type": "STRING",
                        "description": "A very brief note about sentence/word length or structure."
                    }
                },
                "required": ["label", "notes"]
            },
            "strengths": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "2 to 5 specific strengths of the post."
            },
            "improvements": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "2 to 5 specific things to improve."
            },
            "rewrite": {
                "type": "STRING",
                "description": "An improved version of the post. Apply the requested tone preference if specified. Use \\n for line breaks."
            },
            "hooks": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "3 alternative scroll-stopping opening lines matching the requested tone preference."
            },
            "cta": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "2 to 3 suggested calls to action matching the requested tone preference."
            },
            "hashtags": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "3 to 8 relevant hashtags (each starting with '#')."
            },
            "summary": {
                "type": "STRING",
                "description": "One sentence summary of the post's current state."
            }
        },
        "required": [
            "engagement_score",
            "tone",
            "readability",
            "strengths",
            "improvements",
            "rewrite",
            "hooks",
            "cta",
            "hashtags",
            "summary"
        ]
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": text[:8000]}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [
                {"text": sys_instruction}
            ]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AnalysisError(f"Gemini analysis request failed: {exc}") from exc

    try:
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_text)
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"Failed to parse Gemini response: {exc}") from exc

    parsed["source"] = "gemini"
    return parsed


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def analyze(text: str, tone_preference: str | None = None) -> dict:
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if gemini_key:
        try:
            return run_gemini_analysis(text, gemini_key, tone_preference)
        except AnalysisError:
            # Fall back to Anthropic if configured, else heuristics
            if anthropic_key:
                try:
                    return run_ai_analysis(text, anthropic_key, tone_preference)
                except AnalysisError:
                    pass
            result = run_heuristic_analysis(text, tone_preference)
            result["source"] = "heuristic-fallback"
            return result

    if anthropic_key:
        try:
            return run_ai_analysis(text, anthropic_key, tone_preference)
        except AnalysisError:
            result = run_heuristic_analysis(text, tone_preference)
            result["source"] = "heuristic-fallback"
            return result

    return run_heuristic_analysis(text, tone_preference)
