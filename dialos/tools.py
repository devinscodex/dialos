"""Model-facing tools over a project's uploaded files. Read-only.

Every call is scoped to one user's one project; paths are resolved inside that
project's file tree and nothing else is reachable.
"""
import base64

from . import extract, files as filesmod

SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_project_files",
        "description": "List files and folders in the current project's uploaded files. Folders end with '/'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Folder to list, relative to the project root. Default '.'"}}}}},
    {"type": "function", "function": {
        "name": "read_project_file",
        "description": ("Read a text file from the project (documents are stored as '<name>.extracted.txt'). "
                        "Long files are returned in pages; if next_offset is set, call again with that offset."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File path relative to the project root"},
            "offset": {"type": "integer", "description": "Character offset to continue from. Default 0"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_project_files",
        "description": "Case-insensitive text search across the project's files. Returns file, line number and a snippet.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "path": {"type": "string", "description": "Limit to this file or folder. Default whole project"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_project_image",
        "description": "Look at an image file (png, jpg, gif, webp) from the project. The image is attached to the conversation.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

IMAGE_MAX_BYTES = 6 * 1024 * 1024


def run(fl, ns, pid, name, args, char_budget):
    """Returns (result_text, image_b64_or_None, label). Never raises on bad input."""
    args = args if isinstance(args, dict) else {}
    path = str(args.get("path") or ".")
    try:
        if name == "list_project_files":
            r = fl.list_dir(ns, pid, path)
            text = "\n".join(r["entries"]) or "(empty folder)"
            if r["truncated"]:
                text += f"\n(only the first {filesmod.LIST_MAX} entries are shown)"
            return text, None, path
        if name == "read_project_file":
            r = fl.read(ns, pid, path, args.get("offset") or 0, max(500, min(char_budget, 20000)))
            text = r["content"]
            if r.get("next_offset") is not None:
                text += f"\n[more follows: call read_project_file again with offset={r['next_offset']}]"
            return text, None, path
        if name == "search_project_files":
            r = fl.search(ns, pid, str(args.get("query") or ""), path if args.get("path") else ".")
            if not r["matches"]:
                return "no matches", None, str(args.get("query"))[:60]
            lines = [f"{m['path']}:{m['line']}: {m['text']}" for m in r["matches"]]
            if r["truncated"]:
                lines.append("(more matches exist; narrow the search)")
            return "\n".join(lines), None, str(args.get("query"))[:60]
        if name == "read_project_image":
            target = fl.resolve(ns, pid, path)
            if not target.is_file() or extract.kind_of(target.name) != "image":
                return f"error: {path!r} is not an image file", None, path
            if target.stat().st_size > IMAGE_MAX_BYTES:
                return f"error: image is over {IMAGE_MAX_BYTES // 2**20} MB and cannot be shown to the model", None, path
            return "the image is attached to the next message", base64.b64encode(target.read_bytes()).decode(), path
        return f"error: unknown tool {name!r}", None, name
    except (ValueError, TypeError):
        return "error: invalid arguments", None, path
    except filesmod.FileError as e:
        return f"error: {e.message}", None, path
    except OSError:
        return "error: could not read that file", None, path
