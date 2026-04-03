// Centralized API helpers

const API_BASE = "/api";

function getToken() {
  return sessionStorage.getItem("hec_token");
}

function setToken(token) {
  sessionStorage.setItem("hec_token", token);
}

function clearToken() {
  sessionStorage.removeItem("hec_token");
}

function isTokenValid() {
  const token = getToken();
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = {
    ...options.headers,
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = "/index.html";
    throw new Error("Unauthorized");
  }

  return res;
}

/**
 * Stream a chat response via POST + ReadableStream (SSE).
 * @param {string} path
 * @param {object} body
 * @param {(delta: string) => void} onDelta
 * @param {() => void} onDone
 * @param {(err: string) => void} onError
 */
async function apiStream(path, body, onDelta, onDone, onError) {
  let res;
  try {
    res = await apiFetch(path, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (err) {
    onError && onError(err.message);
    return;
  }

  if (!res.ok) {
    const text = await res.text();
    onError && onError(`Server error ${res.status}: ${text}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // keep incomplete line

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(trimmed.slice(6));
        if (data.error) {
          onError && onError(data.error);
          return;
        }
        if (data.done) {
          onDone && onDone();
          return;
        }
        if (data.delta) {
          onDelta && onDelta(data.delta);
        }
      } catch {
        // skip malformed lines
      }
    }
  }
  onDone && onDone();
}

export { getToken, setToken, clearToken, isTokenValid, apiFetch, apiStream };
