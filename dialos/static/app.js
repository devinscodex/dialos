"use strict";
const $ = (id) => document.getElementById(id);
const state = { me: null, history: [], busy: false, abort: null, model: "" };

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
  const me = state.me;
  $("brand").textContent = me.instance_name;
  document.title = me.instance_name;
  $("who").textContent = me.authenticated ? me.name : "";
  $("logout").hidden = !(me.authenticated && me.provider !== "none");
  $("newChat").hidden = !me.authenticated;
  $("auth").hidden = me.authenticated;
  $("chat").hidden = !me.authenticated;
  if (!me.authenticated) {
    $("authTitle").textContent = me.needs_setup ? "Create the first admin account" : "Sign in";
    $("authBtn").textContent = me.needs_setup ? "Create account" : "Sign in";
    $("p").autocomplete = me.needs_setup ? "new-password" : "current-password";
    $("u").focus();
  } else {
    await loadModels();
    $("box").focus();
  }
}

async function loadModels() {
  $("modelBar").hidden = !state.me.model_choice;
  try {
    const m = await api("/api/models");
    state.model = m.default || m.models[0] || "";
    if (state.me.model_choice) {
      const sel = $("model");
      sel.replaceChildren(...m.models.map((n) => new Option(n, n)));
      if (m.default && m.models.includes(m.default)) sel.value = m.default;
    }
    $("chatErr").textContent = (m.models.length || !state.me.model_choice) ? "" : "No models found on the backend.";
  } catch (e) { $("chatErr").textContent = e.message; }
}

function currentModel() { return state.me.model_choice ? $("model").value : state.model; }

$("authForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("authErr").textContent = "";
  $("authBtn").disabled = true;
  try {
    await api(state.me.needs_setup ? "/api/setup" : "/api/login", { username: $("u").value, password: $("p").value });
    $("p").value = "";
    await boot();
  } catch (e) { $("authErr").textContent = e.message; }
  $("authBtn").disabled = false;
});

function resetChat() { state.history = []; $("log").replaceChildren(); $("chatErr").textContent = ""; }
function stopStream() { if (state.abort) state.abort.abort(); }

$("logout").addEventListener("click", async () => {
  stopStream();
  await api("/api/logout", {});
  resetChat();
  await boot();
});
$("newChat").addEventListener("click", () => { stopStream(); resetChat(); $("box").focus(); });
$("stopBtn").addEventListener("click", stopStream);

function scrollDown() { const l = $("log"); l.scrollTop = l.scrollHeight; }

function setBusy(on) {
  state.busy = on;
  $("sendBtn").hidden = on;
  $("stopBtn").hidden = !on;
}

// Renders text with ``` fenced code blocks. Everything goes through textContent.
function renderText(el, text) {
  el.replaceChildren();
  text.split("```").forEach((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf("\n");
      const hasLang = nl >= 0 && /^[\w+#.-]*$/.test(part.slice(0, nl).trim());
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = (hasLang ? part.slice(nl + 1) : part).replace(/\n$/, "");
      pre.appendChild(code);
      el.appendChild(pre);
    } else if (part.trim() !== "") {
      const p = document.createElement("p");
      p.textContent = part.replace(/^\n+|\n+$/g, "");
      el.appendChild(p);
    }
  });
}

function bubble(role) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  $("log").appendChild(d);
  scrollDown();
  return d;
}

$("send").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (state.busy) return;
  const text = $("box").value.trim();
  const model = currentModel();
  if (!text || !model) return;
  $("box").value = "";
  autoGrow();
  $("chatErr").textContent = "";
  state.history.push({ role: "user", content: text });
  const userBubble = bubble("user");
  userBubble.textContent = text;
  const undoSend = () => { state.history.pop(); userBubble.remove(); $("box").value = text; autoGrow(); };

  const out = bubble("assistant");
  const status = document.createElement("div");
  status.className = "status";
  const label = document.createElement("span");
  label.textContent = "Waiting for the model";
  const dots = document.createElement("span");
  dots.className = "dots";
  status.append(label, dots);
  out.appendChild(status);

  let think = null, thinkBody = null, thinkText = "", reply = "";
  const body = document.createElement("div");
  const ctl = new AbortController();
  state.abort = ctl;
  setBusy(true);
  const clearStatus = () => { if (status.parentNode) status.remove(); };
  try {
    const r = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: state.history }), signal: ctl.signal,
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || ("HTTP " + r.status));
    out.appendChild(body);
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
        if (ev2.status === "loading") { label.textContent = "Loading the model"; continue; }
        if (ev2.thinking) {
          clearStatus();
          if (!think) {
            think = document.createElement("details");
            think.className = "think";
            const sum = document.createElement("summary");
            sum.textContent = "Thinking";
            thinkBody = document.createElement("div");
            think.append(sum, thinkBody);
            out.insertBefore(think, body);
          }
          thinkText += ev2.thinking;
          thinkBody.textContent = thinkText;
        }
        if (ev2.content) { clearStatus(); reply += ev2.content; renderText(body, reply); }
        scrollDown();
      }
    }
    clearStatus();
    if (!reply.trim()) renderText(body, "(no reply)");
    state.history.push({ role: "assistant", content: reply });
  } catch (e) {
    clearStatus();
    if (e.name === "AbortError") {
      if (reply.trim()) state.history.push({ role: "assistant", content: reply });
      else { out.remove(); undoSend(); }
    } else {
      $("chatErr").textContent = e.message;
      if (reply.trim()) state.history.push({ role: "assistant", content: reply });
      else { out.remove(); undoSend(); }
    }
  }
  state.abort = null;
  setBusy(false);
  $("box").focus();
});

function autoGrow() {
  const b = $("box");
  b.style.height = "auto";
  b.style.height = Math.min(b.scrollHeight, window.innerHeight * 0.4) + "px";
}
$("box").addEventListener("input", autoGrow);
$("box").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); $("send").requestSubmit(); }
});

boot();
