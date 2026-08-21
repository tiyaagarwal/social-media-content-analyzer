"""
Social Media Content Analyzer - Flask application.

Endpoints:
  GET  /                 -> serves the single-page frontend
  POST /api/extract      -> accepts a PDF/image upload, returns extracted text
  POST /api/analyze      -> accepts text, returns engagement analysis
  GET  /api/health       -> simple health check
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from analyzer.analysis import AnalysisError, analyze
from analyzer.extraction import ExtractionError, SUPPORTED_IMAGE_TYPES, extract

MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB
ALLOWED_EXTENSIONS = {"pdf"} | SUPPORTED_IMAGE_TYPES

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def _allowed_filename(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    ai_configured = bool(gemini_key or anthropic_key)
    provider = "gemini" if gemini_key else ("anthropic" if anthropic_key else "none")
    return jsonify({
        "status": "ok",
        "ai_configured": ai_configured,
        "provider": provider
    })


@app.route("/api/extract", methods=["POST"])
def api_extract():
    if "file" not in request.files:
        return jsonify({"error": "No file was uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file was selected."}), 400

    if not _allowed_filename(file.filename):
        ext = file.filename.rsplit(".", 1)[-1].upper() if "." in file.filename else "unknown"
        return jsonify({
            "error": f"Unsupported file type '.{ext}'. Upload a PDF, PNG, JPG, or JPEG file."
        }), 400

    data = file.read()

    try:
        result = extract(data, file.filename, file.content_type or "")
    except ExtractionError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        app.logger.exception("Unexpected extraction failure")
        return jsonify({"error": f"Unexpected error while processing the file: {exc}"}), 500

    return jsonify({
        "filename": file.filename,
        "text": result.text,
        "method": result.method,
        "page_count": result.page_count,
        "word_count": result.word_count,
        "char_count": result.char_count,
        "warnings": result.warnings,
    })


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    tone = (payload.get("tone") or "").strip() or None

    if not text:
        return jsonify({"error": "No text was provided to analyze."}), 400
    if len(text) > 20000:
        return jsonify({"error": "Text is too long to analyze (20,000 character limit)."}), 400

    try:
        result = analyze(text, tone_preference=tone)
    except AnalysisError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Unexpected analysis failure")
        return jsonify({"error": f"Unexpected error while analyzing the text: {exc}"}), 500

    return jsonify(result)


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_exc):
    return jsonify({"error": "File is too large. Maximum upload size is 15 MB."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
