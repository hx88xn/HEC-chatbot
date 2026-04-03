import { setToken, isTokenValid } from "./api.js";

// If already logged in, redirect to app
if (isTokenValid()) {
  window.location.href = "/app.html";
}

const form = document.getElementById("login-form");
const errorEl = document.getElementById("login-error");
const btn = document.getElementById("btn-login");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;

  if (!username || !password) return;

  setLoading(true);
  errorEl.classList.remove("visible");

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      setToken(data.access_token);
      window.location.href = "/app.html";
    } else {
      const data = await res.json().catch(() => ({}));
      showError(data.detail || "Invalid username or password.");
    }
  } catch {
    showError("Connection error. Please check your network and try again.");
  } finally {
    setLoading(false);
  }
});

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.add("visible");
}

function setLoading(loading) {
  btn.disabled = loading;
  btn.innerHTML = loading
    ? '<span class="spinner"></span> Signing in...'
    : "Sign In";
}
