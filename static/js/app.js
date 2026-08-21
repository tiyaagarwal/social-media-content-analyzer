(() => {
  "use strict";

  const MAX_SIZE_BYTES = 15 * 1024 * 1024;
  const ALLOWED_EXT = ["pdf", "png", "jpg", "jpeg", "webp", "bmp", "tiff"];

  const el = (id) => document.getElementById(id);

  // Theme elements
  const themeToggle = el("theme-toggle");
  const sunIcon = document.querySelector(".sun-icon");
  const moonIcon = document.querySelector(".moon-icon");

  // File Upload Elements
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

  // Section Elements
  const uploadSection = el("upload-section");
  const processingSection = el("processing-section");
  const processingText = el("processing-text");
  const extractSection = el("extract-section");
  const extractMeta = el("extract-meta");
  const extractWarning = el("extract-warning");
  const extractedTextArea = el("extracted-text");
  const analyzeBtn = el("analyze-btn");
  const startOverBtn = el("start-over-btn");

  // Stats badges
  const charCountBadge = el("char-count-badge");
  const wordCountBadge = el("word-count-badge");

  // Tone elements
  const toneOptions = el("tone-options");
  let selectedTone = "";

  // Analyzing & Error Elements
  const analyzingSection = el("analyzing-section");
  const analysisErrorSection = el("analysis-error-section");
  const analysisErrorText = el("analysis-error-text");
  const retryAnalyzeBtn = el("retry-analyze-btn");

  // Results Elements
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

  // Rewrite Stats & Previews
  const rewriteCharCount = el("rewrite-char-count");
  const rewriteWordCount = el("rewrite-word-count");

  // Platform previews
  const linkedinBody = el("linkedin-preview-body");
  const linkedinImageContainer = el("linkedin-image-container");
  const linkedinImg = el("linkedin-preview-img");

  const twitterBody = el("twitter-preview-body");
  const twitterImageContainer = el("twitter-image-container");
  const twitterImg = el("twitter-preview-img");

  const instagramBody = el("instagram-preview-body");
  const instagramPlaceholderCard = el("instagram-placeholder-card");
  const instagramImg = el("instagram-preview-img");
  const instagramScoreNumber = el("instagram-score-number");

  let selectedFile = null;
  let fileObjectURL = null;
  const SCORE_RING_CIRCUMFERENCE = 370.7;

  // -----------------------------------------------------------------------
  // Theme Switching
  // -----------------------------------------------------------------------
  function initTheme() {
    const savedTheme = localStorage.getItem("theme");
    const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    
    if (savedTheme === "dark" || (!savedTheme && systemPrefersDark)) {
      document.body.classList.add("dark-mode");
      sunIcon.style.display = "none";
      moonIcon.style.display = "block";
    } else {
      document.body.classList.remove("dark-mode");
      sunIcon.style.display = "block";
      moonIcon.style.display = "none";
    }
  }

  themeToggle.addEventListener("click", () => {
    const isDark = document.body.classList.toggle("dark-mode");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    
    if (isDark) {
      sunIcon.style.display = "none";
      moonIcon.style.display = "block";
    } else {
      sunIcon.style.display = "block";
      moonIcon.style.display = "none";
    }
  });

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

  function updateInputStats() {
    const text = extractedTextArea.value;
    const charCount = text.length;
    const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
    charCountBadge.textContent = `${charCount} character${charCount === 1 ? "" : "s"}`;
    wordCountBadge.textContent = `${wordCount} word${wordCount === 1 ? "" : "s"}`;
  }

  function updateRewriteStats() {
    const text = rewriteText.value;
    const charCount = text.length;
    const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
    rewriteCharCount.textContent = `${charCount} character${charCount === 1 ? "" : "s"}`;
    rewriteWordCount.textContent = `${wordCount} word${wordCount === 1 ? "" : "s"}`;
    
    // Update live previews
    linkedinBody.textContent = text;
    twitterBody.textContent = text;
    instagramBody.textContent = text;
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

    // Clean old object URL
    if (fileObjectURL) {
      URL.revokeObjectURL(fileObjectURL);
      fileObjectURL = null;
    }

    selectedFile = file;
    
    // Create new ObjectURL if image for social mockups preview
    if (file.type.startsWith("image/")) {
      fileObjectURL = URL.createObjectURL(file);
    }

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
    if (fileObjectURL) {
      URL.revokeObjectURL(fileObjectURL);
      fileObjectURL = null;
    }
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
    updateInputStats();
    showOnly(extractSection);
  }

  extractedTextArea.addEventListener("input", updateInputStats);

  // Tone selector bindings
  toneOptions.addEventListener("click", (e) => {
    const btn = e.target.closest(".tone-btn");
    if (!btn) return;
    
    toneOptions.querySelectorAll(".tone-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedTone = btn.dataset.tone;
  });

  startOverBtn.addEventListener("click", resetToUpload);

  function resetToUpload() {
    selectedFile = null;
    if (fileObjectURL) {
      URL.revokeObjectURL(fileObjectURL);
      fileObjectURL = null;
    }
    fileInput.value = "";
    extractBtn.disabled = true;
    dropzoneIdle.hidden = false;
    dropzoneFile.hidden = true;
    setUploadError(null);
    selectedTone = "";
    toneOptions.querySelectorAll(".tone-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tone === "");
    });
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
        body: JSON.stringify({ text, tone: selectedTone }),
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
    instagramScoreNumber.textContent = score;

    // Color code the score ring and number
    let scoreColor = "var(--rose)";
    if (score >= 80) {
      scoreColor = "var(--emerald)";
    } else if (score >= 50) {
      scoreColor = "var(--amber)";
    }
    scoreRingFill.style.stroke = scoreColor;
    scoreNumber.style.background = scoreColor;
    scoreNumber.style.webkitBackgroundClip = "text";
    scoreNumber.style.webkitTextFillColor = "transparent";

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

    rewriteText.value = data.rewrite || "";
    updateRewriteStats();

    fillList(hooksList, data.hooks, "li");
    fillList(ctaList, data.cta, "li");

    clearListChildren(hashtagsList);
    (data.hashtags || []).forEach((tag) => {
      const span = document.createElement("span");
      span.className = "chip";
      span.textContent = tag.startsWith("#") ? tag : `#${tag}`;
      hashtagsList.appendChild(span);
    });

    // Populate and show Mockup Images if we have them
    if (fileObjectURL) {
      linkedinImageContainer.style.display = "block";
      linkedinImg.src = fileObjectURL;

      twitterImageContainer.style.display = "block";
      twitterImg.src = fileObjectURL;

      instagramPlaceholderCard.style.display = "none";
      instagramImg.style.display = "block";
      instagramImg.src = fileObjectURL;
    } else {
      linkedinImageContainer.style.display = "none";
      linkedinImg.src = "";

      twitterImageContainer.style.display = "none";
      twitterImg.src = "";

      instagramPlaceholderCard.style.display = "flex";
      instagramImg.style.display = "none";
      instagramImg.src = "";
    }

    // Default to the text rewrite tab
    document.querySelectorAll(".preview-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.target === "rewrite-edit-panel");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === "rewrite-edit-panel");
    });

    showOnly(resultsSection);
  }

  // Rewrite edit listener to keep previews in sync
  rewriteText.addEventListener("input", updateRewriteStats);

  // Tab switcher logic
  document.querySelectorAll(".preview-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.target;
      
      // Update tabs
      document.querySelectorAll(".preview-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      
      // Update panels
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === targetId);
      });
    });
  });

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
      await navigator.clipboard.writeText(rewriteText.value);
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
    initTheme();
    try {
      const resp = await fetch("/api/health");
      const data = await resp.json();
      if (data.ai_configured) {
        const providerName = data.provider === "gemini" ? "Gemini API" : "Claude API";
        aiModeHint.textContent = `AI-powered analysis is active (${providerName}).`;
      } else {
        aiModeHint.textContent = "Running on the built-in analysis engine (no AI key configured).";
      }
    } catch (_err) {
      aiModeHint.textContent = "";
    }
  })();
})();
