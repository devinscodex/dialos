"""Conversation and project endpoints (the contract the web UI speaks).

Chat streams newline-delimited JSON events:
  {"type": "status", "status": "loading"}
  {"type": "thinking_delta", "text": ...}   {"type": "content_delta", "text": ...}
  {"type": "tool_call", "name": ..., "args": ..., "output": ...}
  {"type": "done", "model": ..., "title": ..., "ts": ...}   {"type": "error", "error": ...}
"""
import base64
import json
import queue
import re
import sys
import threading
import time

from . import backends, store

MAX_MESSAGE = 200_000
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TITLE = 120
MAX_INSTRUCTIONS = 20_000

_CONV = re.compile(r"^/api/conversations(?:/([^/]+))?(?:/([a-z-]+))?$")
_PROJ = re.compile(r"^/api/projects(?:/([^/]+))?(?:/([a-z-]+))?$")


def auto_title(message: str) -> str:
    line = next((l.strip() for l in message.splitlines() if l.strip()), "New chat")
    return line[:60] + ("…" if len(line) > 60 else "")


def _summary_conv(c):
    return {"id": c["id"], "title": c["title"], "updated": c["updated"], "project_id": c.get("project_id")}


def _summary_proj(p):
    return {"id": p["id"], "name": p["name"], "created": p["created"]}


def handle(h, method, path):
    """Returns True if the request was handled."""
    m = _CONV.match(path)
    if m:
        return _conversations(h, method, m.group(1), m.group(2))
    m = _PROJ.match(path)
    if m:
        return _projects(h, method, m.group(1), m.group(2))
    return False


def _need_user(h):
    ident = h._identity()
    if not ident:
        h._json(401, {"error": "sign in required"})
        return None
    return ident


def _load(h, ns, kind, obj_id, label):
    try:
        return h.app.store.load(ns, kind, obj_id)
    except store.NotFound:
        h._json(404, {"error": f"no such {label}"})
        return None


def _conversations(h, method, conv_id, action):
    ident = _need_user(h)
    if ident is None:
        return True
    st, ns = h.app.store, store.ns_for(ident.id)
    now = time.time()
    if conv_id is None:
        if method == "GET":
            convs = sorted((_summary_conv(c) for c in st.list(ns, "conversations")),
                           key=lambda c: c["updated"], reverse=True)
            h._json(200, {"conversations": convs})
        elif method == "POST":
            body = h._body()
            if body is None:
                return True
            pid = body.get("project_id")
            if pid:
                try:
                    st.load(ns, "projects", pid)
                except store.NotFound:
                    pid = None
            conv = {"id": store.new_id(), "title": "New chat", "created": now, "updated": now,
                    "model": h.app.cfg.default_model, "messages": [], "project_id": pid}
            st.save(ns, "conversations", conv)
            h._json(200, conv)
        else:
            h._json(405, {"error": "method not allowed"})
        return True

    if method == "GET" and action is None:
        conv = _load(h, ns, "conversations", conv_id, "conversation")
        if conv:
            h._json(200, conv)
        return True
    if method == "DELETE" and action is None:
        try:
            st.delete(ns, "conversations", conv_id)
        except store.NotFound:
            return h._json(404, {"error": "no such conversation"}) or True
        h._json(200, {"deleted": conv_id})
        return True
    if method != "POST" or action is None:
        h._json(404, {"error": "not found"})
        return True

    conv = _load(h, ns, "conversations", conv_id, "conversation")
    if conv is None:
        return True
    body = h._body()
    if body is None:
        return True
    if action == "rename":
        title = str(body.get("title") or "").strip()
        if not title:
            return h._json(400, {"error": "title cannot be blank"}) or True
        conv["title"] = title[:MAX_TITLE]
    elif action == "set-project":
        pid = body.get("project_id")
        if pid is not None:
            try:
                st.load(ns, "projects", pid)
            except store.NotFound:
                return h._json(404, {"error": "no such project"}) or True
        conv["project_id"] = pid
    elif action == "truncate":
        try:
            idx = int(body["index"])
        except (KeyError, TypeError, ValueError):
            return h._json(400, {"error": "expected {index: <int>}"}) or True
        if not 0 <= idx <= len(conv["messages"]):
            return h._json(400, {"error": "index out of range"}) or True
        conv["messages"] = conv["messages"][:idx]
    elif action == "chat":
        return _chat(h, st, ns, conv, body)
    elif action == "regenerate":
        return _regenerate(h, st, ns, conv)
    else:
        h._json(404, {"error": "not found"})
        return True
    conv["updated"] = now
    st.save(ns, "conversations", conv)
    h._json(200, conv)
    return True


def _projects(h, method, proj_id, action):
    ident = _need_user(h)
    if ident is None:
        return True
    st, ns = h.app.store, store.ns_for(ident.id)
    if proj_id is None:
        if method == "GET":
            projs = sorted((_summary_proj(p) for p in st.list(ns, "projects")), key=lambda p: p["created"])
            h._json(200, {"projects": projs})
        elif method == "POST":
            body = h._body()
            if body is None:
                return True
            name = str(body.get("name") or "").strip()
            if not name:
                return h._json(400, {"error": "expected {name}"}) or True
            proj = {"id": store.new_id(), "name": name[:MAX_TITLE], "created": time.time(), "instructions": ""}
            st.save(ns, "projects", proj)
            h._json(200, proj)
        else:
            h._json(405, {"error": "method not allowed"})
        return True
    if method == "GET" and action is None:
        proj = _load(h, ns, "projects", proj_id, "project")
        if proj:
            h._json(200, proj)
        return True
    if method == "DELETE" and action is None:
        try:
            st.delete(ns, "projects", proj_id)
        except store.NotFound:
            return h._json(404, {"error": "no such project"}) or True
        for c in st.list(ns, "conversations"):
            if c.get("project_id") == proj_id:
                c["project_id"] = None
                st.save(ns, "conversations", c)
        h._json(200, {"deleted": proj_id})
        return True
    if method == "POST" and action == "update":
        proj = _load(h, ns, "projects", proj_id, "project")
        if proj is None:
            return True
        body = h._body()
        if body is None:
            return True
        if "name" in body:
            name = str(body["name"] or "").strip()
            if not name:
                return h._json(400, {"error": "name cannot be blank"}) or True
            proj["name"] = name[:MAX_TITLE]
        if "instructions" in body:
            proj["instructions"] = str(body["instructions"] or "").strip()[:MAX_INSTRUCTIONS]
        st.save(ns, "projects", proj)
        h._json(200, proj)
        return True
    h._json(404, {"error": "not found"})
    return True


def build_messages(app, st, ns, conv, history):
    system = app.cfg.system_prompt
    if conv.get("project_id"):
        try:
            instr = st.load(ns, "projects", conv["project_id"]).get("instructions", "")
        except store.NotFound:
            instr = ""
        if instr:
            system = (system + "\n\n" if system else "") + "Project instructions:\n" + instr
    msgs = [{"role": "system", "content": system}] if system else []
    for m in history:
        mm = {"role": m["role"], "content": m["content"]}
        if m.get("images"):
            mm["images"] = [i["data"] for i in m["images"]]
        msgs.append(mm)
    return msgs


def _regenerate(h, st, ns, conv):
    if not conv["messages"] or conv["messages"][-1]["role"] != "assistant":
        return h._json(400, {"error": "nothing to regenerate -- last turn isn't an assistant reply"}) or True
    cfg = h.app.cfg
    model = conv.get("model") or cfg.default_model
    if not model or (cfg.model_allowlist and model not in cfg.model_allowlist):
        return h._json(400, {"error": "invalid model"}) or True
    msgs = build_messages(h.app, st, ns, conv, conv["messages"][:-1])
    content, thinking = "", ""
    try:
        for chunk in h.app.backend().chat_stream(model, msgs, think=True):
            content += chunk.content
            thinking += chunk.thinking
    except backends.BackendError as e:
        return h._json(502, {"error": str(e)}) or True
    ts = time.time()
    msg = {"role": "assistant", "content": content, "ts": ts}
    if thinking:
        msg["thinking"] = thinking
    conv["messages"][-1] = msg
    conv["updated"] = ts
    st.save(ns, "conversations", conv)
    h._json(200, {"reply": content, "model": model, "thinking": thinking or None, "ts": ts})
    return True


def _images(raw):
    """Validated [{data, mime}] or an error string."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_IMAGES:
        return f"at most {MAX_IMAGES} images per message"
    out = []
    for img in raw:
        if not isinstance(img, dict) or not isinstance(img.get("data"), str):
            return 'images must be [{"data": "<base64>", "mime": "image/png"}]'
        mime = img.get("mime") if isinstance(img.get("mime"), str) and img["mime"].startswith("image/") else "image/png"
        try:
            n = len(base64.b64decode(img["data"], validate=True))
        except (ValueError, TypeError):
            return "an image is not valid base64"
        if n > MAX_IMAGE_BYTES:
            return f"an image exceeds {MAX_IMAGE_BYTES} bytes"
        out.append({"data": img["data"], "mime": mime})
    return out


def _chat(h, st, ns, conv, body):
    cfg = h.app.cfg
    text = body.get("message")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE:
        return h._json(400, {"error": 'expected {"message": "..."}'}) or True
    images = _images(body.get("images"))
    if isinstance(images, str):
        return h._json(400, {"error": images}) or True
    model = body.get("model") if cfg.model_choice else cfg.default_model
    model = model or conv.get("model") or cfg.default_model
    if not isinstance(model, str) or not model or (cfg.model_allowlist and model not in cfg.model_allowlist):
        return h._json(400, {"error": "invalid model"}) or True

    conv["model"] = model
    if conv["title"] == "New chat":
        conv["title"] = auto_title(text)
    turn = {"role": "user", "content": text, "ts": time.time()}
    if images:
        turn["images"] = images
    conv["messages"].append(turn)

    msgs = build_messages(h.app, st, ns, conv, conv["messages"])

    q = queue.Queue()
    stop = threading.Event()

    def pump():
        gen = None
        try:
            gen = h.app.backend().chat_stream(model, msgs, think=True)
            for chunk in gen:
                if stop.is_set():
                    break
                q.put(("chunk", chunk))
            q.put(("end", None))
        except backends.BackendError as e:
            q.put(("error", str(e)))
        except Exception as e:
            sys.stderr.write("chat error: %r\n" % (e,))
            q.put(("error", "internal error"))
        finally:
            if gen is not None:
                gen.close()

    threading.Thread(target=pump, daemon=True).start()
    h.send_response(200)
    h.send_header("Content-Type", "application/x-ndjson")
    h.send_header("X-Accel-Buffering", "no")
    h._headers_common()
    h.end_headers()

    gone = False
    content, thinking, error = "", "", None

    def emit(obj):
        nonlocal gone
        if gone:
            return
        try:
            h.wfile.write((json.dumps(obj) + "\n").encode())
            h.wfile.flush()
        except OSError:
            gone = True
            stop.set()

    emit({"type": "status", "status": "loading"})
    while True:
        try:
            kind, val = q.get(timeout=10)
        except queue.Empty:
            if not gone:
                try:
                    h.wfile.write(b"\n")
                    h.wfile.flush()
                except OSError:
                    gone = True
                    stop.set()
            continue
        if kind == "chunk":
            if val.thinking:
                thinking += val.thinking
                emit({"type": "thinking_delta", "text": val.thinking})
            if val.content:
                content += val.content
                emit({"type": "content_delta", "text": val.content})
            if gone:
                break
        elif kind == "error":
            error = val
            break
        else:
            break
    stop.set()

    ts = time.time()
    if content or thinking:
        msg = {"role": "assistant", "content": content, "ts": ts}
        if thinking:
            msg["thinking"] = thinking
        conv["messages"].append(msg)
    conv["updated"] = ts
    st.save(ns, "conversations", conv)
    if error:
        emit({"type": "error", "error": error})
    else:
        emit({"type": "done", "model": model, "title": conv["title"], "ts": ts})
    return True
