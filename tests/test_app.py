"""
Automated tests for the Social Media Content Analyzer.

Run with:  python3 -m unittest discover -s tests -v

Fixtures (a text-layer PDF, a scanned/image-only PDF, and an OCR test
image) are generated on the fly with reportlab/Pillow so nothing binary
needs to be committed to the repo.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from analyzer.analysis import run_heuristic_analysis
from analyzer.extraction import ExtractionError, extract
from app import app


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def make_text_pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 12)
    text = c.beginText(72, 720)
    for line in lines:
        text.textLine(line)
    c.drawText(text)
    c.save()
    return buf.getvalue()


def make_text_image(lines: list[str]) -> bytes:
    img = Image.new("RGB", (900, 60 * len(lines) + 60), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28
        )
    except Exception:
        font = ImageFont.load_default()
    y = 30
    for line in lines:
        draw.text((30, y), line, fill="black", font=font)
        y += 55
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_image_only_pdf(lines: list[str]) -> bytes:
    """A PDF with no embedded text layer, forcing the OCR fallback path."""
    import img2pdf

    return img2pdf.convert(make_text_image(lines))


SAMPLE_LINES = [
    "Just tried the new coffee shop downtown!",
    "The oat milk latte was incredible.",
]


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

class ExtractionTests(unittest.TestCase):
    def test_text_layer_pdf(self):
        data = make_text_pdf(SAMPLE_LINES)
        result = extract(data, "sample.pdf", "application/pdf")
        self.assertEqual(result.method, "pdf-text")
        self.assertIn("coffee shop", result.text)
        self.assertEqual(result.warnings, [])

    def test_scanned_pdf_falls_back_to_ocr(self):
        data = make_image_only_pdf(SAMPLE_LINES)
        result = extract(data, "scanned.pdf", "application/pdf")
        self.assertEqual(result.method, "pdf-ocr")
        self.assertIn("coffee", result.text.lower())
        self.assertTrue(result.warnings)

    def test_image_ocr(self):
        data = make_text_image(SAMPLE_LINES)
        result = extract(data, "sample.png", "image/png")
        self.assertEqual(result.method, "image-ocr")
        self.assertIn("coffee", result.text.lower())

    def test_unsupported_type_raises(self):
        with self.assertRaises(ExtractionError):
            extract(b"hello", "notes.txt", "text/plain")

    def test_empty_pdf_raises(self):
        with self.assertRaises(ExtractionError):
            extract(b"", "empty.pdf", "application/pdf")

    def test_corrupted_pdf_raises(self):
        with self.assertRaises(ExtractionError):
            extract(b"not a real pdf", "broken.pdf", "application/pdf")

    def test_corrupted_image_raises(self):
        with self.assertRaises(ExtractionError):
            extract(b"not a real image", "broken.png", "image/png")


# ---------------------------------------------------------------------------
# Analysis tests
# ---------------------------------------------------------------------------

class AnalysisTests(unittest.TestCase):
    def test_returns_all_expected_keys(self):
        result = run_heuristic_analysis("This is a simple test post about hiking trails.")
        for key in [
            "engagement_score", "tone", "readability", "strengths",
            "improvements", "rewrite", "hooks", "cta", "hashtags", "summary",
        ]:
            self.assertIn(key, result)

    def test_score_in_valid_range(self):
        result = run_heuristic_analysis("Check out our new product line, available now!")
        self.assertGreaterEqual(result["engagement_score"], 1)
        self.assertLessEqual(result["engagement_score"], 100)

    def test_strong_hook_is_preserved_in_rewrite(self):
        text = "Did you know 90% of startups fail in year one? Here's why."
        result = run_heuristic_analysis(text)
        self.assertIn("Did you know 90%", result["rewrite"])

    def test_weak_hook_gets_replaced_in_rewrite(self):
        text = "We released a new update. It has several small fixes."
        result = run_heuristic_analysis(text)
        self.assertNotEqual(result["rewrite"].splitlines()[0], "We released a new update.")

    def test_existing_cta_detected(self):
        text = "Great news! Comment below to let us know what you think."
        result = run_heuristic_analysis(text)
        self.assertTrue(any("call-to-action" in s.lower() for s in result["strengths"]))

    def test_two_different_inputs_produce_different_output(self):
        a = run_heuristic_analysis("Short punchy hook! Buy now, link in bio. #sale #deal")
        b = run_heuristic_analysis(
            "A long, meandering paragraph with no clear point, no hashtags, "
            "no call to action, and no real hook to speak of, unfortunately."
        )
        self.assertNotEqual(a["engagement_score"], b["engagement_score"])
        self.assertNotEqual(a["rewrite"], b["rewrite"])

    def test_heuristic_tone_preference_professional(self):
        text = "This is a simple post about learning coding."
        res = run_heuristic_analysis(text, tone_preference="professional")
        self.assertIn("Regarding the growth and impact", res["rewrite"])

    def test_heuristic_tone_preference_hype(self):
        text = "This is a simple post about learning coding."
        res = run_heuristic_analysis(text, tone_preference="hype")
        self.assertIn("Huge shift happening", res["rewrite"])
        self.assertIn("🚀", res["rewrite"])


# ---------------------------------------------------------------------------
# Flask endpoint tests
# ---------------------------------------------------------------------------

class AppEndpointTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("status", resp.get_json())

    def test_homepage_renders(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Content", resp.data)

    def test_extract_endpoint_with_pdf(self):
        data = make_text_pdf(SAMPLE_LINES)
        resp = self.client.post(
            "/api/extract",
            data={"file": (io.BytesIO(data), "sample.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("coffee shop", body["text"])

    def test_extract_endpoint_rejects_bad_type(self):
        resp = self.client.post(
            "/api/extract",
            data={"file": (io.BytesIO(b"hi"), "notes.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)

    def test_extract_endpoint_requires_file(self):
        resp = self.client.post("/api/extract", data={}, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)

    def test_analyze_endpoint(self):
        resp = self.client.post("/api/analyze", json={"text": "A short test caption about running."})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("engagement_score", body)

    def test_analyze_endpoint_with_tone(self):
        resp = self.client.post(
            "/api/analyze",
            json={"text": "A short test caption about running.", "tone": "witty"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("engagement_score", body)

    def test_analyze_endpoint_requires_text(self):
        resp = self.client.post("/api/analyze", json={"text": ""})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
