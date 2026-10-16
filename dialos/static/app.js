"use strict";
const $ = (id) => document.getElementById(id);
let state = { me: null, history: [] };

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

async function boot() {
  state.me = await api("/api/me");
  $("brand").textContent = state.me.instance_name;
  document.title = state.me.instance_name;
  $("who").textContent = state.me.authenticated ? state.me.name : "";
  $("logout").hidden = !(state.me.authenticated && state.me.provider !== "none");
  $("auth").hidden = state.me.authenticated;
  $("chat").hidden = !state.me.authenticated;
  if (!state.me.authenticated) {
    $("authTitle").textContent = state.me.needs_setup ? "Create the first admin account" : "Sign in";
    $("authBtn").textContent = state.me.needs_setup ? "Create account" : "Sign in";
    $("p").autocomplete = state.me.needs_setup ? "new-password" : "current-password";
  } else {
    loadModels();
  }
}

async function loadModels() {
  try {
    const m = await api("/api/models");
    const sel = $("model");
    sel.replaceChildren(...m.models.map((n) => new Option(n, n)));
    if (m.default && m.models.includes(m.default)) sel.value = m.default;
    $("chatErr").textContent = m.models.length ? "" : "No models found on the backend.";
  } catch (e) { $("chatErr").textContent = e.message; }
}

$("authForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("authErr").textContent = "";
  try {
    await api(state.me.needs_setup ? "/api/setup" : "/api/login", { username: $("u").value, password: $("p").value });
    $("p").value = "";
    await boot();
  } catch (e) { $("authErr").textContent = e.message; }
});

$("logout").addEventListener("click", async () => {
  await api("/api/logout", {});
  state.history = [];
  $("log").replaceChildren();
  await boot();
});

function bubble(role) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  $("log").appendChild(d);
  $("log").scrollTop = $("log").scrollHeight;
  return d;
}

$("send").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const text = $("box").value.trim();
  if (!text || !$("model").value) return;
  $("box").value = "";
  $("chatErr").textContent = "";
  state.history.push({ role: "user", content: text });
  bubble("user").textContent = text;
  const out = bubble("assistant");
  const think = document.createElement("div");
  think.className = "think";
  const body = document.createElement("div");
  out.append(think, body);
  let reply = "";
  try {
    const r = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: $("model").value, messages: state.history }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || ("HTTP " + r.status));
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev2 = JSON.parse(line.slice(6));
        if (ev2.error) throw new Error(ev2.error);
        if (ev2.thinking) think.textContent += ev2.thinking;
        if (ev2.content) { reply += ev2.content; body.textContent = reply; }
        $("log").scrollTop = $("log").scrollHeight;
      }
    }
    state.history.push({ role: "assistant", content: reply });
  } catch (e) {
    $("chatErr").textContent = e.message;
    state.history.pop();
  }
});

$("box").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); $("send").requestSubmit(); }
});

boot();
