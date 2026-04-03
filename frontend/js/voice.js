import { apiFetch } from "./api.js";
import { showToast } from "./app.js";

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

export function initVoice(sessionId, onTranscript) {
  const btnVoice = document.getElementById("btn-voice");
  const transcribingEl = document.getElementById("transcribing-indicator");

  function startRecording() {
    if (isRecording) return;

    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        isRecording = true;
        audioChunks = [];

        // Pick best supported format
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")
          ? "audio/ogg;codecs=opus"
          : "audio/webm";

        mediaRecorder = new MediaRecorder(stream, { mimeType });
        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };
        mediaRecorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(audioChunks, { type: mimeType });
          transcribeAudio(blob, mimeType, sessionId, onTranscript, transcribingEl);
        };

        mediaRecorder.start(100); // collect data every 100ms
        btnVoice.classList.add("recording");
        btnVoice.title = "Release to send";
      })
      .catch(() => {
        showToast("Microphone access denied. Please allow microphone permissions.", "error");
      });
  }

  function stopRecording() {
    if (!isRecording || !mediaRecorder) return;
    isRecording = false;
    btnVoice.classList.remove("recording");
    btnVoice.title = "Hold to Record";
    if (mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
  }

  // Desktop: hold to record
  btnVoice.addEventListener("mousedown", (e) => {
    e.preventDefault();
    startRecording();
  });

  btnVoice.addEventListener("mouseup", stopRecording);
  btnVoice.addEventListener("mouseleave", stopRecording);

  // Mobile: touch
  btnVoice.addEventListener("touchstart", (e) => {
    e.preventDefault();
    startRecording();
  });

  btnVoice.addEventListener("touchend", (e) => {
    e.preventDefault();
    stopRecording();
  });
}

async function transcribeAudio(blob, mimeType, sessionId, onTranscript, transcribingEl) {
  transcribingEl.classList.add("visible");

  const ext = mimeType.includes("ogg") ? "ogg" : "webm";
  const formData = new FormData();
  formData.append("audio", blob, `recording.${ext}`);
  formData.append("session_id", sessionId);

  try {
    const res = await apiFetch("/transcribe", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (res.ok && data.transcript) {
      onTranscript(data.transcript);
    } else {
      showToast(data.detail || "Transcription failed. Please try typing instead.", "error");
    }
  } catch {
    showToast("Transcription error. Please try typing your message.", "error");
  } finally {
    transcribingEl.classList.remove("visible");
  }
}
