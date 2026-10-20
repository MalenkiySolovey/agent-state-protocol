# Security policy

Agent State Protocol defines data shapes, not a credential vault or transport security boundary.

- Never put secret values in a protocol message or example. Use `SecretReference` and credential metadata only.
- Keep repository examples synthetic. Do not submit real account identifiers, endpoints, local paths, tokens, API keys, TOTP material, or vault data.
- Sanitize `ErrorDetail.message` and `details` before serialization; schema validation cannot determine whether arbitrary text contains a secret.
- Consumers are responsible for protecting local transport, authenticating peers where needed, and securing data at rest.
- This repository does not define or promise credential-at-rest storage, process isolation, authorization, or daemon security properties.
- A user-selected account nickname may itself identify a person and may contain `@`; treat it as potentially sensitive user data. It is distinct from an email-derived fallback, which must not be transmitted as `safeFallbackDisplayName`.

When reporting a vulnerability, do not include live credentials or private account data. Use GitHub's private vulnerability reporting for this repository when available; otherwise contact the maintainers privately through the repository's GitHub contact options.
