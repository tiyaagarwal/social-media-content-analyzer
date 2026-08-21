(() => {
  "use strict";

  const MAX_SIZE_BYTES = 15 * 1024 * 1024;
  const ALLOWED_EXT = ["pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff"];

  const el = (id) => document.getElementById(id);

  const dropzone = el("dropzone");
  const fileInput = el("file-input");
  const dropzoneIdle = el("dropzone-idle");
  const dropzoneFile = el("dropzone-file");
  const fileNameEl = el("file-name");
  const fileSizeEl = el("file-size");
  const changeFileBtn = el("change-file-btn");
  const uploadError = el("upload-error");
  const extractBtn = el("extract-btn");
  const aiModeHint = el("ai-mode-hint");

  const uploadSection = el("upload-section");
  const processingSection = el("processing-section");
  const processingText = el("processing-text");
  const extractSection = el("extract-section");
  const extractMeta = el("extract-meta");
  const extractWarning = el("extract-warning");
  const extractedTextArea = el("extracted-text");
  const analyzeBtn = el("analyze-btn");
  const startOverBtn = el("start-over-btn");

  const analyzingSection = el("analyzing-section");
  const analysisErrorSection = el("analysis-error-section");
  const analysisErrorText = el("analysis-error-text");
  const retryAnalyzeBtn = el("retry-analyze-btn");

  const resultsSection = el("results-section");
  const scoreNumber = el("score-number");
  const scoreRingFill = el("score-ring-fill");
  const resultsSummary = el("results-summary");
  const toneChip = el("tone-chip");
  const readabilityChip = el("readability-chip");
  const strengthsList = el("strengths-list");
  const improvementsList = el("improvements-list");
  const rewriteText = el("rewrite-text");
  const copyRewriteBtn = el("copy-rewrite-btn");
  const hooksList = el("hooks-list");
  const ctaList = el("cta-list");
  const hashtagsList = el("hashtags-list");
  const analyzeAnotherBtn = el("analyze-another-btn");

  let selectedFile = null;
  const SCORE_RING_CIRCUMFERENCE = 370.7;

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  function showOnly(...visibleSections) {
    const all = [
      uploadSection, processingSection, extractSection,
      analyzingSection, analysisErrorSection, resultsSection,
    ];
    all.forEach((s) => { s.hidden = !visibleSections.includes(s); });
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function extOf(filename) {
    const parts = filename.split(".");
    return parts.length > 1 ? parts.pop().toLowerCase() : "";
  }

  function setUploadError(message) {
    if (!message) {
      uploadError.hidden = true;
      uploadError.textContent = "";
      return;
    }
    uploadError.hidden = false;
    uploadError.textContent = message;
  }

  function clearListChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  // -----------------------------------------------------------------------
  // File selection
  // -----------------------------------------------------------------------

  function handleFileSelected(file) {
    setUploadError(null);

    if (!file) return;

    const ext = extOf(file.name);
    if (!ALLOWED_EXT.includes(ext)) {
      setUploadError(`Unsupported file type ".${ext || "unknown"}". Upload a PDF, PNG, JPG, JPEG, WEBP, BMP, or TIFF file.`);
      selectedFile = null;
      extractBtn.disabled = true;
      return;
    }

    if (file.size > MAX_SIZE_BYTES) {
      setUploadError(`This file is ${formatBytes(file.size)}, which is over the 15 MB limit.`);
      selectedFile = null;
      extractBtn.disabled = true;
      return;
    }

    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatBytes(file.size);
    dropzoneIdle.hidden = true;
    dropzoneFile.hidden = false;
    extractBtn.disabled = false;
  }

  dropzone.addEventListener("click", (e) => {
    if (e.target.closest("#change-file-btn")) return;
    fileInput.click();
  });

  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) {
      handleFileSelected(fileInput.files[0]);
    }
  });

  changeFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.value = "";
    selectedFile = null;
    extractBtn.disabled = true;
    dropzoneIdle.hidden = false;
    dropzoneFile.hidden = true;
    setUploadError(null);
    fileInput.click();
  });

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("is-dragover");
    });
  });

  ["dragleave", "dragend"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("is-dragover");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("is-dragover");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleFileSelected(file);
  });

  // -----------------------------------------------------------------------
  // Extraction
  // -----------------------------------------------------------------------

  extractBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    showOnly(processingSection);
    processingText.textContent = selectedFile.name.toLowerCase().endsWith(".pdf")
      ? "Reading your PDF…"
      : "Running OCR on your image…";

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const resp = await fetch("/api/extract", { method: "POST", body: formData });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || "Extraction failed.");
      }

      renderExtracted(data);
    } catch (err) {
      showOnly(uploadSection);
      setUploadError(err.message || "Something went wrong while extracting text.");
    }
  });

  function renderExtracted(data) {
    clearListChildren(extractMeta);

    const methodLabel = {
      "pdf-text": "PDF text layer",
      "pdf-ocr": "PDF · OCR",
      "image-ocr": "Image · OCR",
    }[data.method] || data.method;

    const chips = [
      methodLabel,
      `${data.word_count} words`,
      `${data.page_count} page${data.page_count === 1 ? "" : "s"}`,
    ];
    chips.forEach((c) => {
      const span = document.createElement("span");
      span.textContent = c;
      extractMeta.appendChild(span);
    });

    if (data.warnings && data.warnings.length) {
      extractWarning.hidden = false;
      extractWarning.textContent = data.warnings.join(" ");
    } else {
      extractWarning.hidden = true;
    }

    extractedTextArea.value = data.text;
    showOnly(extractSection);
  }

  startOverBtn.addEventListener("click", resetToUpload);

  function resetToUpload() {
    selectedFile = null;
    fileInput.value = "";
    extractBtn.disabled = true;
    dropzoneIdle.hidden = false;
    dropzoneFile.hidden = true;
    setUploadError(null);
    showOnly(uploadSection);
  }

  // -----------------------------------------------------------------------
  // Analysis
  // -----------------------------------------------------------------------

  async function runAnalysis() {
    const text = extractedTextArea.value.trim();
    if (!text) return;

    showOnly(analyzingSection);

    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || "Analysis failed.");
      }

      renderResults(data);
    } catch (err) {
      showOnly(analysisErrorSection);
      analysisErrorText.textContent = err.message || "Something went wrong while analyzing this content.";
    }
  }

  analyzeBtn.addEventListener("click", runAnalysis);
  retryAnalyzeBtn.addEventListener("click", runAnalysis);

  function renderResults(data) {
    const score = Math.max(0, Math.min(100, Math.round(data.engagement_score || 0)));
    scoreNumber.textContent = score;
    const offset = SCORE_RING_CIRCUMFERENCE * (1 - score / 100);
    // Trigger transition on next frame
    scoreRingFill.style.strokeDashoffset = String(SCORE_RING_CIRCUMFERENCE);
    requestAnimationFrame(() => {
      scoreRingFill.style.strokeDashoffset = String(offset);
    });

    resultsSummary.textContent = data.summary || "";
    toneChip.textContent = `Tone — ${data.tone || "—"}`;

    const readability = data.readability || {};
    const readLabel = readability.label || readability.notes || "—";
    readabilityChip.textContent = `Readability — ${readLabel}`;

    fillList(strengthsList, data.strengths, "li");
    fillList(improvementsList, data.improvements, "li");

    rewriteText.textContent = data.rewrite || "";

    fillList(hooksList, data.hooks, "li");
    fillList(ctaList, data.cta, "li");

    clearListChildren(hashtagsList);
    (data.hashtags || []).forEach((tag) => {
      const span = document.createElement("span");
      span.className = "chip";
      span.textContent = tag.startsWith("#") ? tag : `#${tag}`;
      hashtagsList.appendChild(span);
    });

    showOnly(resultsSection);
  }

  function fillList(node, items, tag) {
    clearListChildren(node);
    (items || []).forEach((item) => {
      const li = document.createElement(tag);
      li.textContent = item;
      node.appendChild(li);
    });
  }

  copyRewriteBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(rewriteText.textContent);
      const original = copyRewriteBtn.textContent;
      copyRewriteBtn.textContent = "Copied";
      setTimeout(() => { copyRewriteBtn.textContent = original; }, 1500);
    } catch (_err) {
      /* clipboard API unavailable — silently ignore */
    }
  });

  analyzeAnotherBtn.addEventListener("click", resetToUpload);

  // -----------------------------------------------------------------------
  // Init
  // -----------------------------------------------------------------------

  (async function init() {
    try {
      const resp = await fetch("/api/health");
      const data = await resp.json();
      aiModeHint.textContent = data.ai_configured
        ? "AI-powered analysis is active."
        : "Running on the built-in analysis engine (no AI key configured).";
    } catch (_err) {
      aiModeHint.textContent = "";
    }
  })();
})();
