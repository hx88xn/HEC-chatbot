import { isTokenValid, clearToken } from "./api.js";
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

// Initialize marksheet upload
initMarksheet(sessionId, (summary) => {
  // Transition to chat
  uploadSection.style.display = "none";
  chatSection.classList.add("visible");
  stepUpload.classList.remove("active");
  stepUpload.classList.add("done");
  stepUpload.querySelector(".step-num").textContent = "✓";
  stepChat.classList.add("active");

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
