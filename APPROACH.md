# Approach

The brief had two real problems: reliably getting text out of arbitrary uploads, and turning that text into feedback that's actually specific to it.

For extraction, I didn't want to ask the user whether their PDF was "scanned" — so the backend tries the embedded text layer first (`pdfplumber`) and automatically falls back to rasterizing pages and running OCR (`pypdfium2` + Tesseract) when that layer is empty or too sparse to be real content. Images go through the same OCR path directly.

For analysis, a static/templated response would have failed the brief's own bar ("genuinely useful, not a static mock"). I built a rule-based engine that reads the actual text — sentence and syllable counts for readability, regex/lexicon scans for existing hooks, CTAs, hashtags, and emoji, and frequency-based keyword extraction — and uses those signals to score engagement and generate a rewrite that keeps a strong opening line intact rather than blindly overwriting it. It's structured so a configured `ANTHROPIC_API_KEY` swaps in Claude-generated analysis with the same output shape, with automatic fallback to the rule-based engine if that call fails.

Kept the frontend to vanilla HTML/CSS/JS — no build step, minimal dependencies, easy to reason about end to end.

(196 words)
