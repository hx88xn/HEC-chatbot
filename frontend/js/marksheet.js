import { apiFetch } from "./api.js";

export function initMarksheet(sessionId, onSuccess) {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const fileInfo = document.getElementById("file-selected-info");
  const fileNameEl = document.getElementById("file-name");
  const fileSizeEl = document.getElementById("file-size");
  const btnRemove = document.getElementById("btn-remove-file");
  const btnUpload = document.getElementById("btn-upload");
  const uploadStatus = document.getElementById("upload-status");

  let selectedFile = null;

  // Drag and drop events
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) selectFile(file);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) selectFile(fileInput.files[0]);
  });

  btnRemove.addEventListener("click", (e) => {
    e.stopPropagation();
    clearFile();
  });

  btnUpload.addEventListener("click", () => {
    if (selectedFile) uploadFile(selectedFile);
  });

  function selectFile(file) {
    const allowed = ["application/pdf", "image/jpeg", "image/jpg", "image/png", "image/webp"];
    if (!allowed.includes(file.type) && !file.name.match(/\.(pdf|jpg|jpeg|png|webp)$/i)) {
      showStatus("error", "Unsupported file type. Please upload a PDF, JPG, or PNG.");
      return;
    }

    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatSize(file.size);
    fileInfo.classList.add("visible");
    btnUpload.disabled = false;
    hideStatus();
  }

  function clearFile() {
    selectedFile = null;
    fileInput.value = "";
    fileInfo.classList.remove("visible");
    btnUpload.disabled = true;
    hideStatus();
  }

  async function uploadFile(file) {
    btnUpload.disabled = true;
    showStatus("uploading", "Analyzing your marksheet with AI...");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("session_id", sessionId);

    try {
      const res = await apiFetch("/marksheet/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (res.ok) {
        showSuccess(data.summary);
      } else {
        showStatus("error", data.detail || "Upload failed. Please try again.");
        btnUpload.disabled = false;
      }
    } catch (err) {
      showStatus("error", "Connection error. Please try again.");
      btnUpload.disabled = false;
    }
  }

  function showStatus(type, message) {
    uploadStatus.className = `upload-status ${type}`;

    if (type === "uploading") {
      uploadStatus.innerHTML = `
        <span class="spinner dark"></span>
        <span>${message}</span>
      `;
    } else if (type === "error") {
      uploadStatus.innerHTML = `
        <svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <span>${message}</span>
      `;
    }
  }

  function showSuccess(summary) {
    uploadStatus.className = "upload-status success";
    uploadStatus.innerHTML = `
      <div class="success-header">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
        Marksheet analyzed successfully
      </div>
      <div class="success-summary">${escapeHtml(summary)}</div>
      <button class="btn-continue" id="btn-continue">
        Continue to Career Counselling
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="5" y1="12" x2="19" y2="12"/>
          <polyline points="12 5 19 12 12 19"/>
        </svg>
      </button>
    `;

    document.getElementById("btn-continue").addEventListener("click", () => {
      onSuccess(summary);
    });
  }

  function hideStatus() {
    uploadStatus.className = "upload-status";
    uploadStatus.innerHTML = "";
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
}
