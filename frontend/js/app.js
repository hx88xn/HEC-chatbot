import { isTokenValid, clearToken, apiFetch } from "./api.js";
import { initMarksheet } from "./marksheet.js";
import { initChat, sendTextMessage, triggerGreeting } from "./chat.js";
import { initVoice } from "./voice.js";

// Guard: redirect to login if not authenticated
if (!isTokenValid()) {
  clearToken();
  window.location.href = "/index.html";
}

// Session ID: persist in sessionStorage for this tab
let sessionId = sessionStorage.getItem("hec_session_id");
if (!sessionId) {
  sessionId = crypto.randomUUID();
  sessionStorage.setItem("hec_session_id", sessionId);
}

// Display session ID in sidebar
document.getElementById("session-id-display").textContent = sessionId.slice(0, 8) + "...";

// Step indicators
const stepUpload = document.getElementById("step-upload");
const stepChat = document.getElementById("step-chat");

// Sections
const uploadSection = document.getElementById("upload-section");
const chatSection = document.getElementById("chat-section");

// Analysis Elements
const btnAnalyze = document.getElementById("btn-analyze");
const analysisModal = document.getElementById("analysis-modal");
const btnCloseAnalysis = document.getElementById("btn-close-analysis");
const analysisLoading = document.getElementById("analysis-loading");
const analysisResults = document.getElementById("analysis-results");

// Initialize marksheet upload
initMarksheet(sessionId, (summary) => {
  // Transition to chat
  uploadSection.style.display = "none";
  chatSection.classList.add("visible");
  stepUpload.classList.remove("active");
  stepUpload.classList.add("done");
  stepUpload.querySelector(".step-num").textContent = "✓";
  stepChat.classList.add("active");
  
  // Enable the analyze button now that session has started
  btnAnalyze.disabled = false;

  // Initialize chat + voice
  initChat(sessionId);
  initVoice(sessionId, (transcript) => {
    sendTextMessage(transcript);
  });

  // Trigger AI greeting
  triggerGreeting();
});

// Logout
document.getElementById("btn-logout").addEventListener("click", () => {
  clearToken();
  sessionStorage.clear();
  window.location.href = "/index.html";
});

// New Session
document.getElementById("btn-new-session").addEventListener("click", () => {
  if (confirm("Start a new session? Your current conversation will be lost.")) {
    sessionStorage.removeItem("hec_session_id");
    window.location.reload();
  }
});

// ── Session Analysis ─────────────────────────────────────

btnAnalyze.addEventListener("click", async () => {
  analysisModal.style.display = "flex";
  analysisLoading.style.display = "flex";
  analysisResults.style.display = "none";
  analysisResults.innerHTML = "";
  btnAnalyze.disabled = true;

  try {
    const res = await apiFetch(`/chat/analysis/${sessionId}`);
    const data = await res.json();

    if (!res.ok) {
      renderAnalysisError(data.detail || "Analysis failed.");
      return;
    }

    if (data.error) {
      renderAnalysisError(data.error);
      return;
    }

    renderAnalysisResults(data);
  } catch (err) {
    renderAnalysisError("Connection error. Please try again.");
  } finally {
    analysisLoading.style.display = "none";
    btnAnalyze.disabled = false;
  }
});

btnCloseAnalysis.addEventListener("click", () => {
  analysisModal.style.display = "none";
});

analysisModal.addEventListener("click", (e) => {
  if (e.target === analysisModal) analysisModal.style.display = "none";
});

function renderAnalysisResults(data) {
  const categories = [
    {
      key: "core_counseling",
      title: "Core Counseling Performance",
      labels: {
        intent_recognition_accuracy: "Intent Recognition Accuracy",
        career_fit_analysis_quality: "Career Fit Analysis Quality",
        task_completion_rate: "Task Completion Rate",
        marksheet_context_utilization: "Marksheet Context Utilization",
      },
    },
    {
      key: "conversational_quality",
      title: "Conversational Quality",
      labels: {
        context_retention: "Context Retention",
        tone_appropriateness: "Tone Appropriateness",
        empathy_score: "Empathy Score",
        clarity: "Clarity",
      },
    },
    {
      key: "compliance_and_ux",
      title: "Compliance & UX",
      labels: {
        student_confusion_rate: "Student Confusion Rate",
        hec_guidelines_adherence: "HEC Guidelines Adherence",
      },
    },
  ];

  let html = "";

  for (const cat of categories) {
    const section = data[cat.key];
    if (!section) continue;

    html += `<div class="analysis-category">`;
    html += `<div class="analysis-category-title">${cat.title}</div>`;
    html += `<div class="kpi-grid">`;

    for (const [field, label] of Object.entries(cat.labels)) {
      const value = section[field] || "N/A";
      const numericValue = parseInt(value);
      const colorClass = getScoreColor(numericValue);
      html += `
        <div class="kpi-item">
          <span class="kpi-label">${label}</span>
          <span class="kpi-value ${colorClass}">${escapeHtml(value)}</span>
          ${!isNaN(numericValue) ? `<div class="kpi-bar"><div class="kpi-bar-fill ${colorClass}" style="width: ${numericValue}%"></div></div>` : ""}
        </div>`;
    }

    html += `</div></div>`;
  }

  if (data.summary) {
    html += `
      <div class="analysis-category">
        <div class="analysis-category-title">Session Summary</div>
        <div class="analysis-summary">${escapeHtml(data.summary)}</div>
      </div>`;
  }

  analysisResults.innerHTML = html;
  analysisResults.style.display = "block";
}

function renderAnalysisError(message) {
  analysisLoading.style.display = "none";
  analysisResults.innerHTML = `
    <div style="text-align:center;padding:32px 0;color:var(--error);">
      <p style="font-size:14px;font-weight:600;margin-bottom:6px;">Analysis Failed</p>
      <p style="font-size:13px;color:var(--text-secondary);">${escapeHtml(message)}</p>
    </div>`;
  analysisResults.style.display = "block";
}

function getScoreColor(value) {
  if (isNaN(value)) return "";
  if (value >= 80) return "score-high";
  if (value >= 60) return "score-mid";
  return "score-low";
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Toast notification system
const toastContainer = document.getElementById("toast-container");

export function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(() => toast.remove(), 350);
  }, 4000);
}
