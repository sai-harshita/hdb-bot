const state = {
  token: localStorage.getItem("hdb_bot_token") || "",
  username: localStorage.getItem("hdb_bot_username") || "",
};

const loginForm = document.getElementById("loginForm");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const messages = document.getElementById("messages");
const topicsList = document.getElementById("topicsList");
const refreshTopics = document.getElementById("refreshTopics");
const authState = document.getElementById("authState");
const statusPill = document.getElementById("statusPill");
const loginButton = document.getElementById("loginButton");
const sendButton = document.getElementById("sendButton");

function setStatus(connected) {
  statusPill.textContent = connected ? `Connected as ${state.username}` : "Disconnected";
  statusPill.classList.toggle("connected", connected);
}

function addMessage(role, body, meta = []) {
  const card = document.createElement("article");
  card.className = `message ${role}`;

  const heading = document.createElement("div");
  heading.className = "message-head";
  heading.innerHTML = `<span>${role}</span><span>${new Date().toLocaleTimeString()}</span>`;

  const content = document.createElement("div");
  content.className = "message-body";
  content.textContent = body;

  card.append(heading, content);

  if (meta.length) {
    const metaWrap = document.createElement("div");
    metaWrap.className = "message-meta";
    for (const item of meta) {
      const chip = document.createElement("span");
      chip.className = "meta-chip";
      chip.textContent = item;
      metaWrap.appendChild(chip);
    }
    card.appendChild(metaWrap);
  }

  messages.appendChild(card);
  messages.scrollTop = messages.scrollHeight;
}

async function loadTopics() {
  topicsList.innerHTML = "";
  try {
    const response = await fetch("/api/topics");
    const data = await response.json();
    for (const topic of data.topics || []) {
      const item = document.createElement("li");
      item.textContent = topic;
      topicsList.appendChild(item);
    }
  } catch {
    const item = document.createElement("li");
    item.textContent = "Topics unavailable until the API is running.";
    topicsList.appendChild(item);
  }
}

async function loadHistory() {
  if (!state.token) return;
  try {
    const response = await fetch("/api/chat/history", {
      headers: {
        Authorization: `Bearer ${state.token}`,
      },
    });
    if (!response.ok) return;
    const items = await response.json();
    messages.innerHTML = "";
    items.reverse().forEach((item) => {
      addMessage("user", item.question);
      addMessage(
        "assistant",
        item.answer,
        [
          item.blocked_by ? `blocked:${item.blocked_by}` : "allowed",
          item.created_at ? new Date(item.created_at).toLocaleString() : "stored",
        ],
      );
    });
  } catch {
    // Ignore history failures on first load.
  }
}

async function login(event) {
  event.preventDefault();
  loginButton.disabled = true;
  authState.textContent = "Signing in...";

  try {
    const formData = new URLSearchParams(new FormData(loginForm));
    const response = await fetch("/api/auth/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: formData,
    });

    if (!response.ok) {
      throw new Error("Login failed");
    }

    const data = await response.json();
    state.token = data.access_token;
    state.username = data.username;
    localStorage.setItem("hdb_bot_token", state.token);
    localStorage.setItem("hdb_bot_username", state.username);
    authState.textContent = `Authenticated as ${state.username}.`;
    setStatus(true);
    addMessage("system", `Signed in as ${state.username}. You can now query the HDB assistant.`);
    await loadHistory();
  } catch (error) {
    authState.textContent = "Login failed. Check the API and your credentials.";
    setStatus(false);
  } finally {
    loginButton.disabled = false;
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || !state.token) {
    if (!state.token) {
      addMessage("system", "Sign in first. The chatbot requires a JWT.");
    }
    return;
  }

  messageInput.value = "";
  addMessage("user", text);
  sendButton.disabled = true;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${state.token}`,
      },
      body: JSON.stringify({ message: text }),
    });

    if (!response.ok) {
      throw new Error("Chat request failed");
    }

    const data = await response.json();
    const meta = [];
    meta.push(data.blocked_by ? `blocked:${data.blocked_by}` : "guardrails:passed");
    if (data.agent_used) meta.push("eligibility-agent");
    (data.sources || []).slice(0, 4).forEach((source) => meta.push(source));
    addMessage("assistant", data.answer, meta);
  } catch (error) {
    addMessage("system", "The request failed. Check whether Docker, Ollama, and the API stack are running.");
  } finally {
    sendButton.disabled = false;
  }
}

refreshTopics.addEventListener("click", loadTopics);
loginForm.addEventListener("submit", login);
chatForm.addEventListener("submit", sendMessage);

loadTopics();
setStatus(Boolean(state.token && state.username));

if (state.token && state.username) {
  authState.textContent = `Restored prior session for ${state.username}.`;
  loadHistory();
} else {
  addMessage("system", "Sign in with the demo account to start testing the local HDB assistant.");
}
