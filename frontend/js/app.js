import { isTokenValid, clearToken, apiFetch } from "./api.js";
import { initMarksheet } from "./marksheet.js";
import { initChat, sendTextMessage, triggerGreeting } from "./chat.js";
import { initVoice } from "./voice.js";
import { startVoiceCall, endVoiceCall } from "./voice-call.js";

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

// Voice call section
const voiceCallSection = document.getElementById("voice-call-section");

// Initialize marksheet upload
initMarksheet(sessionId, (summary, mode) => {
  // Mark upload step done
  uploadSection.style.display = "none";
  stepUpload.classList.remove("active");
  stepUpload.classList.add("done");
  stepUpload.querySelector(".step-num").textContent = "✓";
  stepChat.classList.add("active");

  // Enable the analyze button now that session has started
  btnAnalyze.disabled = false;

  if (mode === "voice") {
    // Start voice call mode
    startVoiceCall(sessionId);
  } else {
    // Default: text chat mode
    chatSection.classList.add("visible");
    initChat(sessionId);
    initVoice(sessionId, (transcript) => {
      sendTextMessage(transcript);
    });
    triggerGreeting();
  }
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

// Voice analysis inline elements
const voiceAnalysisSection = document.getElementById("voice-analysis-section");
const voiceAnalysisLoading = document.getElementById("voice-analysis-loading");
const voiceAnalysisResults = document.getElementById("voice-analysis-results");

/** Open analysis as a modal popup (used by "Analyze Session" button in chat mode) */
export async function openAnalysisModal() {
  analysisModal.style.display = "flex";
  analysisLoading.style.display = "flex";
  analysisResults.style.display = "none";
  analysisResults.innerHTML = "";
  btnAnalyze.disabled = true;

  try {
    const data = await fetchAnalysis();
    renderAnalysisInto(analysisResults, data);
  } catch (err) {
    renderAnalysisErrorInto(analysisResults, err);
  } finally {
    analysisLoading.style.display = "none";
    btnAnalyze.disabled = false;
  }
}

/** Open analysis as a full inline screen (used after voice call ends) */
export async function openVoiceAnalysis() {
  voiceAnalysisSection.classList.add("visible");
  voiceAnalysisLoading.style.display = "flex";
  voiceAnalysisResults.style.display = "none";
  voiceAnalysisResults.innerHTML = "";

  try {
    const data = await fetchAnalysis();
    renderAnalysisInto(voiceAnalysisResults, data);
  } catch (err) {
    renderAnalysisErrorInto(voiceAnalysisResults, err);
  } finally {
    voiceAnalysisLoading.style.display = "none";
  }
}

async function fetchAnalysis() {
  const res = await apiFetch(`/chat/analysis/${sessionId}`);
  const data = await res.json();
  if (!res.ok) throw data.detail || "Analysis failed.";
  if (data.error) throw data.error;
  return data;
}

btnAnalyze.addEventListener("click", openAnalysisModal);

btnCloseAnalysis.addEventListener("click", () => {
  analysisModal.style.display = "none";
});

analysisModal.addEventListener("click", (e) => {
  if (e.target === analysisModal) analysisModal.style.display = "none";
});

function renderAnalysisInto(container, data) {
  container.innerHTML = buildAnalysisHtml(data);
  container.style.display = "block";
}

function renderAnalysisErrorInto(container, message) {
  container.innerHTML = `
    <div style="text-align:center;padding:32px 0;color:var(--error);">
      <p style="font-size:14px;font-weight:600;margin-bottom:6px;">Analysis Failed</p>
      <p style="font-size:13px;color:var(--text-secondary);">${escapeHtml(String(message))}</p>
    </div>`;
  container.style.display = "block";
}

function buildAnalysisHtml(data) {
  const categories = [
    {
      key: "academic_understanding",
      title: "Academic Understanding",
      labels: {
        marksheet_analysis_depth: "Marksheet Analysis Depth",
        subject_strength_identification: "Subject Strength Identification",
        academic_stream_awareness: "Academic Stream Awareness",
      },
    },
    {
      key: "career_guidance_quality",
      title: "Career Guidance Quality",
      labels: {
        career_path_relevance: "Career Path Relevance",
        program_knowledge: "Program & University Knowledge",
        entry_test_guidance: "Entry Test Guidance",
        scholarship_financial_guidance: "Scholarship & Financial Guidance",
        merit_cutoff_awareness: "Merit Cut-off Awareness",
      },
    },
    {
      key: "student_engagement",
      title: "Student Engagement",
      labels: {
        question_quality: "Question Quality",
        personalization: "Personalization",
        empathy_and_encouragement: "Empathy & Encouragement",
        clarity_of_communication: "Clarity of Communication",
      },
    },
    {
      key: "compliance_and_completeness",
      title: "Compliance & Completeness",
      labels: {
        student_confusion_rate: "Student Confusion Rate",
        hec_guidelines_adherence: "HEC Guidelines Adherence",
        session_completeness: "Session Completeness",
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

    // Fields where lower score = better
    const invertedFields = new Set(["student_confusion_rate"]);

    for (const [field, label] of Object.entries(cat.labels)) {
      const value = section[field] || "N/A";
      const numericValue = parseInt(value);
      const inverted = invertedFields.has(field);
      const colorClass = getScoreColor(numericValue, inverted);
      html += `
        <div class="kpi-item">
          <span class="kpi-label">${label}${inverted ? ' <span style="font-size:10px;color:var(--text-muted);">(lower is better)</span>' : ""}</span>
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

  return html;
}

function getScoreColor(value, inverted = false) {
  if (isNaN(value)) return "";
  if (inverted) {
    // Lower is better: <=20 = green, <=40 = yellow, >40 = red
    if (value <= 20) return "score-high";
    if (value <= 40) return "score-mid";
    return "score-low";
  }
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
