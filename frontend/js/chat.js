import { apiStream } from "./api.js";

let sessionId = null;
let isStreaming = false;
const messagesEl = document.getElementById("chat-messages");
const inputEl = document.getElementById("message-input");
const btnSend = document.getElementById("btn-send");

export function initChat(sid) {
  sessionId = sid;

  btnSend.addEventListener("click", sendMessage);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  inputEl.addEventListener("input", () => {
    // Auto-resize textarea
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
    btnSend.disabled = !inputEl.value.trim() || isStreaming;
  });
}

export function sendTextMessage(text) {
  inputEl.value = text;
  sendMessage();
}

/** Trigger AI greeting without showing a user bubble */
export function triggerGreeting() {
  if (isStreaming) return;
  isStreaming = true;
  btnSend.disabled = true;

  const assistantBubble = appendMessage("assistant", "", true);
  scrollToBottom();

  let fullText = "";

  apiStream(
    "/chat/stream",
    { session_id: sessionId, message: "Hello, I have uploaded my marksheet. Please greet me and start the counselling session." },
    (delta) => {
      fullText += delta;
      renderStreamingBubble(assistantBubble, fullText);
      scrollToBottom();
    },
    () => {
      finalizeStreamingBubble(assistantBubble, fullText);
      isStreaming = false;
      btnSend.disabled = false;
      scrollToBottom();
    },
    (err) => {
      finalizeStreamingBubble(assistantBubble, "Welcome! I'm PM Youth Program's Career Counsellor. Let's explore the best career path for you after Intermediate. Could you tell me about your subjects and interests?\n\n[SUGGESTIONS: \"I'm in FSc Pre-Medical\" | \"I'm in FSc Pre-Engineering\" | \"I need help choosing a field\"]");
      isStreaming = false;
      btnSend.disabled = false;
    }
  );
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || isStreaming) return;

  inputEl.value = "";
  inputEl.style.height = "auto";
  btnSend.disabled = true;
  isStreaming = true;

  appendMessage("user", text);

  const assistantBubble = appendMessage("assistant", "", true);
  scrollToBottom();

  let fullText = "";

  await apiStream(
    "/chat/stream",
    { session_id: sessionId, message: text },
    (delta) => {
      fullText += delta;
      renderStreamingBubble(assistantBubble, fullText);
      scrollToBottom();
    },
    () => {
      finalizeStreamingBubble(assistantBubble, fullText);
      isStreaming = false;
      btnSend.disabled = !inputEl.value.trim();
      scrollToBottom();
    },
    (err) => {
      finalizeStreamingBubble(assistantBubble, `Sorry, an error occurred. Please try again.\n\n_${err}_`);
      isStreaming = false;
      btnSend.disabled = !inputEl.value.trim();
    }
  );
}

function appendMessage(role, text, streaming = false) {
  const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const isUser = role === "user";
  const avatarIcon = isUser
    ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
        <circle cx="12" cy="7" r="4"/>
       </svg>`
    : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2a10 10 0 0 1 10 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2z"/>
        <path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/>
        <line x1="15" y1="9" x2="15.01" y2="9"/>
       </svg>`;

  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;
  wrapper.innerHTML = `
    <div class="message-avatar">${avatarIcon}</div>
    <div class="message-content">
      <div class="message-bubble" dir="auto" data-streaming="${streaming}">
        ${streaming ? '<span class="cursor"></span>' : renderMarkdown(text)}
      </div>
      <span class="message-time">${now}</span>
    </div>
  `;

  messagesEl.appendChild(wrapper);
  return wrapper.querySelector(".message-bubble");
}

function renderStreamingBubble(bubble, text) {
  bubble.innerHTML = renderMarkdown(text) + '<span class="cursor"></span>';
}

function finalizeStreamingBubble(bubble, text) {
  bubble.removeAttribute("data-streaming");
  const { cleanText, suggestions } = parseSuggestions(text);
  bubble.innerHTML = renderMarkdown(cleanText);

  if (suggestions.length > 0) {
    const container = document.createElement("div");
    container.className = "suggestion-chips";
    suggestions.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "suggestion-chip";
      chip.textContent = s;
      chip.addEventListener("click", () => {
        container.remove();
        sendTextMessage(s);
      });
      container.appendChild(chip);
    });
    // Insert after the message-content (sibling of bubble's parent)
    const messageContent = bubble.closest(".message-content");
    if (messageContent) {
      messageContent.appendChild(container);
    }
  }
}

function parseSuggestions(text) {
  const match = text.match(/\[SUGGESTIONS:\s*"([^"]+)"(?:\s*\|\s*"([^"]+)")*\s*\]/);
  if (!match) return { cleanText: text, suggestions: [] };

  const fullMatch = match[0];
  const cleanText = text.replace(fullMatch, "").trimEnd();

  // Extract all quoted suggestions
  const suggestions = [];
  const re = /"([^"]+)"/g;
  let m;
  while ((m = re.exec(fullMatch)) !== null) {
    suggestions.push(m[1]);
  }
  return { cleanText, suggestions };
}

function renderMarkdown(text) {
  if (!text) return "";
  return text
    // Bold
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    // Bullet lists
    .replace(/^[-•]\s+(.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
    // Numbered lists
    .replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>")
    // Line breaks → paragraphs
    .split(/\n\n+/)
    .map((p) => {
      p = p.trim();
      if (!p) return "";
      if (p.startsWith("<ul>") || p.startsWith("<li>")) return p;
      return `<p>${p.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

export { sendMessage };
