# Roadmap

Status key: [x] done, [ ] planned. Order within a section is rough priority.

## Foundation
- [x] Config layer: `mode = solo|multi`, fail-closed validation
- [x] Local accounts (scrypt, sessions, lockout) and admin CLI
- [x] Model backends: Ollama and OpenAI-compatible, auto-detected
- [x] HTTP server: login/logout/first-run setup, HttpOnly/SameSite/Secure cookies, CSRF, CSP, streaming chat, model list (minimal UI)
- [ ] Port the full chat interface (conversations, projects, themes) onto the new server
- [ ] Mobile layout (single column, drawer sidebar)
- [ ] Strip instance-specific prompts and tools; move to config

## Auth
- [ ] Generic OIDC provider (Keycloak, Authentik, Zitadel, Pocket ID, Entra, ...)
- [ ] Reverse-proxy provider (oauth2-proxy, Authelia, Cloudflare Access)
- [ ] Passkeys (WebAuthn) for local accounts
- [ ] LDAP bind provider
- [ ] Admin screen in Settings: users, roles, disable, reset

## Users
- [ ] Real user records (full name, role, department, preferences) keyed by
      email, independent of the identity provider, so the assistant knows who
      it is talking to instead of parsing a name from an address

## Settings
- [ ] About: version number, commit, link to release history
- [ ] Toggle for the background grid texture
- [ ] Feedback section (below)
- [ ] Theme list cleanup

## Feedback
- [ ] Settings -> Feedback: category (bug / idea / praise), free text
- [ ] Thumbs up/down on each reply with an optional note
- [ ] Conversation text is attached only when the user opts in per submission
- [ ] Stored per instance in the data dir; admins can list and export
- [ ] Config: `feedback.enabled`, optional notify address

## Files
- [ ] Chunked, streamed upload to disk; per-user quota instead of a fixed 50 MB cap
- [ ] Local folder connection in the browser (File System Access API,
      Chromium) so files are read on demand without uploading
- [ ] Startup report of which file types can be read (pdftotext, tesseract,
      LibreOffice are optional)

## Skills
- [ ] Per-user skill folders of markdown (`SKILL.md` with name and description)
- [ ] Only name and description go in the prompt; a `read_skill` tool loads the body
- [ ] No execution of bundled scripts in v1

## Integrations
- [ ] Microsoft 365 mail (read-only first): summarize what matters, review
      mail rules, flag suspicious messages, alert a configured security address
- [ ] Mail content goes only to local models
