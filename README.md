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

## Context and logging

The full conversation is always kept on disk. Each request sends the model
only the system text plus as many recent messages as fit in about 75% of
`context_tokens`; the page shows a context meter and says when earlier
messages are saved but outside the model's memory.

Dialos writes one JSON line per chat request and sign-in event to
`<data_dir>/logs/events.jsonl` (owner-only, rotated at 20 MB). It records
timings, token counts, model names and outcomes, never message text.

    python -m dialos.stats --days 7
    python -m dialos.stats --days 1 --raw 20

## Tests

    python -m unittest discover -s tests -t .

## License

MIT
