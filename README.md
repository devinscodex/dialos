# Dialos

An open web chat framework for local AI models. Self-hosted, privacy-first,
and usable from any machine that runs a model server.

Status: early. The configuration layer and built-in account system exist;
the web server and model backends are being ported in.

## Design

- **Modes.** `mode = "solo"` is one person on localhost with no login.
  `mode = "multi"` is several people and refuses to start without a real
  auth provider.
- **Auth providers.** `local` (built-in accounts), `oidc` (any OpenID
  Connect issuer: Keycloak, Authentik, Zitadel, Pocket ID, Entra, ...),
  `proxy` (identity from a trusted reverse proxy).
- **Backends.** Ollama and OpenAI-compatible servers (llama.cpp, vLLM,
  LM Studio).
- **No build step.** Python standard library plus optional dependencies.

## Managing local accounts

    python -m dialos.cli list
    python -m dialos.cli add alice --admin
    python -m dialos.cli passwd alice
    python -m dialos.cli role bob admin
    python -m dialos.cli disable bob
    python -m dialos.cli delete bob

## Tests

    python -m unittest discover -s tests -t .

## License

MIT
