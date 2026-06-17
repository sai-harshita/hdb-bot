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
const loadHistoryButton = document.getElementById("loadHistoryButton");
const clearViewButton = document.getElementById("clearViewButton");
const topicCount = document.getElementById("topicCount");
const promptButtons = Array.from(document.querySelectorAll(".prompt-chip"));

function formatRole(role) {
  if (role === "assistant") return "HDB assistant";
  if (role === "user") return "You";
  return "System";
}

function setStatus(connected) {
  statusPill.textContent = connected ? `Connected as ${state.username}` : "Disconnected";
  statusPill.classList.toggle("connected", connected);
}

function clearTranscript(note = "") {
  messages.innerHTML = "";
  if (note) {
    addMessage("system", note);
  }
}

function addMessage(role, body, options = {}) {
  const card = document.createElement("article");
  card.className = `message ${role}`;

  const head = document.createElement("div");
  head.className = "message-head";

  const left = document.createElement("span");
  left.textContent = formatRole(role);
  const right = document.createElement("span");
  right.textContent = options.timestamp || new Date().toLocaleTimeString();
  head.append(left, right);

  const content = document.createElement("div");
  content.className = "message-body";
  content.textContent = body;

  card.append(head, content);

  if (options.badges?.length) {
    const badgeRow = document.createElement("div");
    badgeRow.className = "message-badges";
    options.badges.forEach((badge) => {
      const chip = document.createElement("span");
      chip.className = `message-badge ${badge.kind || ""}`.trim();
      chip.textContent = badge.label;
      badgeRow.appendChild(chip);
    });
    card.appendChild(badgeRow);
  }

  if (options.sources?.length) {
    const sourceWrap = document.createElement("div");
    sourceWrap.className = "sources-block";

    const title = document.createElement("div");
    title.className = "sources-title";
    title.textContent = "Official sources";
    sourceWrap.appendChild(title);

    const list = document.createElement("div");
    list.className = "source-list";
    options.sources.slice(0, 4).forEach((source) => {
      const link = document.createElement("a");
      link.className = "source-link";
      link.href = source;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source;
      list.appendChild(link);
    });
    sourceWrap.appendChild(list);
    card.appendChild(sourceWrap);
  }

  messages.appendChild(card);
  messages.scrollTop = messages.scrollHeight;
}

function setTopicCount(count) {
  topicCount.textContent = `${count} topics`;
}

async function loadTopics() {
  topicsList.innerHTML = "";
  try {
    const response = await fetch("/api/topics");
    const data = await response.json();
    const topics = data.topics || [];
    setTopicCount(topics.length);
    topics.forEach((topic) => {
      const item = document.createElement("li");
      item.textContent = topic;
      topicsList.appendChild(item);
    });
  } catch {
    setTopicCount(0);
    const item = document.createElement("li");
    item.textContent = "Topics unavailable until the API is running.";
    topicsList.appendChild(item);
  }
}

async function loadHistory() {
  if (!state.token) {
    addMessage("system", "Sign in first if you want to inspect stored chat history.");
    return;
  }

  loadHistoryButton.disabled = true;
  try {
    const response = await fetch("/api/chat/history", {
      headers: {
        Authorization: `Bearer ${state.token}`,
      },
    });
    if (!response.ok) {
      throw new Error("History request failed");
    }

    const items = await response.json();
    if (!items.length) {
      clearTranscript("No stored chat history yet. Ask a fresh HDB question.");
      return;
    }

    messages.innerHTML = "";
    items.reverse().forEach((item) => {
      addMessage("user", item.question, {
        timestamp: item.created_at ? new Date(item.created_at).toLocaleTimeString() : "stored",
      });
      addMessage("assistant", item.answer, {
        timestamp: item.created_at ? new Date(item.created_at).toLocaleTimeString() : "stored",
        badges: [
          item.blocked_by
            ? { label: `blocked:${item.blocked_by}`, kind: "warn" }
            : { label: "stored answer", kind: "ok" },
        ],
      });
    });
  } catch {
    addMessage("system", "Recent history could not be loaded.");
  } finally {
    loadHistoryButton.disabled = false;
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

    setStatus(true);
    authState.textContent = `Authenticated as ${state.username}. Ask a fresh HDB question or load recent history.`;
    clearTranscript(`Signed in as ${state.username}. The assistant is ready for a fresh HDB question.`);
  } catch {
    setStatus(false);
    authState.textContent = "Login failed. Check the API and your credentials.";
  } finally {
    loginButton.disabled = false;
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text) {
    return;
  }

  if (!state.token) {
    addMessage("system", "Sign in first. The chatbot requires a JWT session.");
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
    const badges = [
      data.blocked_by
        ? { label: `blocked:${data.blocked_by}`, kind: "warn" }
        : { label: "guardrails passed", kind: "ok" },
    ];
    if (data.agent_used) {
      badges.push({ label: "eligibility agent", kind: "ok" });
    }

    addMessage("assistant", data.answer, {
      badges,
      sources: data.sources || [],
    });
  } catch {
    addMessage("system", "The request failed. Check whether Docker, Ollama, and the API stack are running.");
  } finally {
    sendButton.disabled = false;
  }
}

function restoreSessionView() {
  loadTopics();
  setStatus(Boolean(state.token && state.username));

  if (state.token && state.username) {
    authState.textContent = `Restored session for ${state.username}. Ask a fresh HDB question or load recent history.`;
    clearTranscript(`Session restored for ${state.username}. Start with a fresh HDB prompt.`);
  } else {
    clearTranscript("Sign in with the demo account to start testing the local HDB assistant.");
  }
}

refreshTopics.addEventListener("click", loadTopics);
loginForm.addEventListener("submit", login);
chatForm.addEventListener("submit", sendMessage);
loadHistoryButton.addEventListener("click", loadHistory);
clearViewButton.addEventListener("click", () => {
  clearTranscript("Transcript cleared. Ask a fresh HDB question.");
});

promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.prompt || "";
    messageInput.focus();
  });
});

restoreSessionView();
