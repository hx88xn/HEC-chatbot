import { getToken } from "./api.js";
import { showToast, openVoiceAnalysis } from "./app.js";

let ws = null;
let micContext = null;
let micSource = null;
let micProc = null;
let playbackContext = null;
let nextPlayTime = 0;
let callActive = false;
let audioQueue = [];
let pendingUserTranscript = "";
let pendingUserBubble = null;

const callSection = document.getElementById("voice-call-section");
const callStatus = document.getElementById("call-status");
const callTimer = document.getElementById("call-timer");
const btnEndCall = document.getElementById("btn-end-call");
const transcriptEl = document.getElementById("call-transcript");

let timerInterval = null;
let callStartTime = null;

// ── Audio helpers ──────────────────────────────────────────

function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  let offset = 0;
  for (let i = 0; i < float32Array.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}

function uint8ToBase64(u8) {
  let s = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < u8.length; i += chunkSize) {
    s += String.fromCharCode.apply(null, u8.subarray(i, i + chunkSize));
  }
  return btoa(s);
}

function base64ToInt16(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

// ── Start Voice Call ──────────────────────────────────────

export async function startVoiceCall(sessionId) {
  callSection.classList.add("visible");
  callStatus.textContent = "Connecting...";
  callTimer.textContent = "00:00";
  transcriptEl.innerHTML = "";
  pendingUserTranscript = "";
  pendingUserBubble = null;

  try {
    // 1. Set up AudioContext for mic capture at 8 kHz (matches g711_ulaw)
    micContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 8000,
    });

    // 2. Set up playback context at 8 kHz
    playbackContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 8000,
    });
    nextPlayTime = 0;

    // 3. Get microphone
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        noiseSuppression: true,
        echoCancellation: true,
        sampleRate: 8000,
      },
    });

    micSource = micContext.createMediaStreamSource(stream);

    // 4. AudioWorklet for capturing + VAD
    const workletCode = `
      class AudioProcessor extends AudioWorkletProcessor {
        constructor() {
          super();
          this.lastVoiceTime = currentTime;
        }
        process(inputs, outputs, parameters) {
          const input = inputs[0];
          if (!input || !input[0]) return true;
          const ch = input[0];
          let sum = 0;
          for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
          const rms = Math.sqrt(sum / ch.length);
          const VOLUME_THRESHOLD = 0.04;
          const HANGOVER_MS = 0.5;
          if (rms > VOLUME_THRESHOLD) {
            this.lastVoiceTime = currentTime;
          }
          const shouldSendAudio =
            rms > VOLUME_THRESHOLD ||
            (currentTime - this.lastVoiceTime) < HANGOVER_MS;
          this.port.postMessage({ audio: ch, sendAudio: shouldSendAudio });
          return true;
        }
      }
      registerProcessor('audio-processor', AudioProcessor);
    `;

    const blob = new Blob([workletCode], { type: "application/javascript" });
    const workletUrl = URL.createObjectURL(blob);
    await micContext.audioWorklet.addModule(workletUrl);
    URL.revokeObjectURL(workletUrl);

    micProc = new AudioWorkletNode(micContext, "audio-processor");
    micSource.connect(micProc);
    micProc.connect(micContext.destination); // needed to keep the worklet alive

    // 5. Connect WebSocket to backend
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/realtime/ws`;
    ws = new WebSocket(wsUrl);

    ws.addEventListener("open", () => {
      // Send start event with auth token + session ID
      ws.send(
        JSON.stringify({
          event: "start",
          start: {
            session_id: sessionId,
            token: getToken(),
          },
        })
      );
    });

    ws.addEventListener("message", (e) => {
      try {
        const data = JSON.parse(e.data);
        handleServerEvent(data);
      } catch {
        // skip malformed
      }
    });

    ws.addEventListener("close", () => {
      if (callActive) endVoiceCall();
    });

    ws.addEventListener("error", () => {
      showToast("Voice connection error", "error");
      endVoiceCall();
    });

    // 6. When AudioWorklet produces audio, ALWAYS send to backend
    //    OpenAI server-side VAD needs a continuous audio stream
    //    (speech AND silence) to detect turn boundaries.
    micProc.port.onmessage = (e) => {
      const { audio, sendAudio } = e.data;
      if (ws && ws.readyState === WebSocket.OPEN && callActive) {
        let b64;
        if (sendAudio) {
          const pcm16 = floatTo16BitPCM(audio);
          b64 = uint8ToBase64(pcm16);
        } else {
          // Send silence (zeros) to keep the stream continuous
          const silence = new Uint8Array(audio.length * 2);
          b64 = uint8ToBase64(silence);
        }
        ws.send(
          JSON.stringify({
            event: "media",
            media: { payload: b64, timestamp: Date.now() },
          })
        );
      }
    };
  } catch (err) {
    showToast(
      err.name === "NotAllowedError"
        ? "Microphone access denied. Please allow microphone permissions."
        : err.message || "Failed to start voice call",
      "error"
    );
    endVoiceCall();
  }
}

// ── Handle events from backend ─────────────────────────────

let currentAssistantTranscript = "";

function handleServerEvent(data) {
  switch (data.event) {
    case "session_ready":
      callActive = true;
      callStatus.textContent = "Connected";
      callSection.classList.add("active");
      startTimer();
      break;

    case "clear":
      // User started speaking — stop all queued AI audio immediately
      clearAudioQueue();
      break;

    case "media":
      playAudioChunk(data.media.payload);
      break;

    case "transcript_delta":
      if (data.role === "assistant") {
        currentAssistantTranscript += data.delta;
        updateStreamingTranscript();
      }
      break;

    case "transcript_done":
      if (data.role === "assistant") {
        finalizeUserBubble();
        finalizeTranscriptEntry("Counsellor", data.transcript || currentAssistantTranscript);
        currentAssistantTranscript = "";
      } else if (data.role === "user" && data.transcript) {
        appendToUserBubble(data.transcript);
      }
      break;

    case "error":
      showToast(data.message || "Voice call error", "error");
      break;
  }
}

function clearAudioQueue() {
  audioQueue.forEach((source) => {
    try {
      source.stop();
    } catch {}
  });
  audioQueue = [];
  if (playbackContext) {
    nextPlayTime = playbackContext.currentTime;
  }
}

// ── Audio playback ────────────────────��─────────────────────

function playAudioChunk(pcmB64) {
  if (!playbackContext) return;

  const int16 = base64ToInt16(pcmB64);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768;
  }

  // Apply simple gain
  const GAIN = 2.0;
  for (let i = 0; i < float32.length; i++) {
    float32[i] = Math.max(-1, Math.min(1, float32[i] * GAIN));
  }

  // Fade in/out to prevent clicks (32 samples)
  const FADE = 32;
  for (let i = 0; i < Math.min(FADE, float32.length); i++) {
    float32[i] *= i / FADE;
  }
  for (let i = 0; i < Math.min(FADE, float32.length); i++) {
    float32[float32.length - 1 - i] *= i / FADE;
  }

  const buffer = playbackContext.createBuffer(1, float32.length, 8000);
  buffer.getChannelData(0).set(float32);

  const source = playbackContext.createBufferSource();
  source.buffer = buffer;
  source.connect(playbackContext.destination);

  const now = playbackContext.currentTime;
  if (nextPlayTime < now) nextPlayTime = now;
  source.start(nextPlayTime);
  nextPlayTime += buffer.duration;

  // Track source so clearAudioQueue can stop it
  audioQueue.push(source);
  source.onended = () => {
    const idx = audioQueue.indexOf(source);
    if (idx > -1) audioQueue.splice(idx, 1);
  };
}

// ── Transcript display ──────────────────────────────────────

function updateStreamingTranscript() {
  let streaming = transcriptEl.querySelector(".streaming");
  if (!streaming) {
    streaming = document.createElement("div");
    streaming.className = "transcript-entry assistant streaming";
    streaming.innerHTML = `<span class="transcript-label">Counsellor</span><span class="transcript-text"></span>`;
    transcriptEl.appendChild(streaming);
  }
  streaming.querySelector(".transcript-text").innerHTML =
    escapeHtml(currentAssistantTranscript) + '<span class="cursor"></span>';
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function finalizeTranscriptEntry(label, text) {
  // Remove streaming entry
  const streaming = transcriptEl.querySelector(".streaming");
  if (streaming) streaming.remove();
  addTranscriptEntry(label, text);
}

function addTranscriptEntry(label, text) {
  const div = document.createElement("div");
  div.className = `transcript-entry ${label === "You" ? "user" : "assistant"}`;
  div.innerHTML = `<span class="transcript-label">${label}</span><span class="transcript-text">${escapeHtml(text)}</span>`;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function appendToUserBubble(text) {
  if (!text || !text.trim()) return;

  if (pendingUserTranscript) {
    pendingUserTranscript += " " + text.trim();
  } else {
    pendingUserTranscript = text.trim();
  }

  if (!pendingUserBubble) {
    pendingUserBubble = document.createElement("div");
    pendingUserBubble.className = "transcript-entry user";
    pendingUserBubble.innerHTML = `<span class="transcript-label">You</span><span class="transcript-text"></span>`;
    // Insert before any streaming assistant entry to maintain correct order
    // (user transcript often arrives after assistant starts streaming)
    const streaming = transcriptEl.querySelector(".streaming");
    if (streaming) {
      transcriptEl.insertBefore(pendingUserBubble, streaming);
    } else {
      transcriptEl.appendChild(pendingUserBubble);
    }
  }

  pendingUserBubble.querySelector(".transcript-text").textContent = pendingUserTranscript;
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function finalizeUserBubble() {
  if (pendingUserTranscript && pendingUserBubble) {
    pendingUserTranscript = "";
    pendingUserBubble = null;
  }
}

// ── Timer ───────────────────────────────────────────────────

function startTimer() {
  callStartTime = Date.now();
  timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
    const mins = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const secs = String(elapsed % 60).padStart(2, "0");
    callTimer.textContent = `${mins}:${secs}`;
  }, 1000);
}

// ── End call ────────────────────────────────────────────────

export function endVoiceCall() {
  callActive = false;
  finalizeUserBubble();

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  // Close mic
  if (micProc) {
    try {
      micProc.disconnect();
    } catch {}
    micProc = null;
  }
  if (micSource) {
    try {
      micSource.disconnect();
      micSource.mediaStream.getTracks().forEach((t) => t.stop());
    } catch {}
    micSource = null;
  }
  if (micContext) {
    try {
      micContext.close();
    } catch {}
    micContext = null;
  }

  // Clear any queued audio and close playback
  clearAudioQueue();
  if (playbackContext) {
    try {
      playbackContext.close();
    } catch {}
    playbackContext = null;
  }

  // Close websocket
  if (ws) {
    try {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ event: "stop" }));
      }
      ws.close();
    } catch {}
    ws = null;
  }

  nextPlayTime = 0;
  currentAssistantTranscript = "";

  callSection.classList.remove("active");
  callSection.classList.remove("visible");
  callStatus.textContent = "Disconnected";
}

btnEndCall.addEventListener("click", () => {
  endVoiceCall();
  showToast("Voice call ended — generating analysis...", "info");
  // Small delay to let backend save transcripts before requesting analysis
  setTimeout(() => openVoiceAnalysis(), 1500);
});

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
