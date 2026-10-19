# Agent State Protocol

Agent State Protocol defines language-neutral JSON schemas for exchanging safe local AI-agent, account, credential-metadata, provider, and usage state.

## What this is

- A transport-neutral contract described by JSON Schema Draft 2020-12.
- A small v1 schema family identified by `schemaVersion: 1`.
- A canonical, synthetic set of examples and a machine-readable schema manifest.

## What this is not

- Credential storage or a place to put secret values.
- A daemon, database, RPC server, UI library, or Codex-specific configuration format.
- A language SDK or generated application model.

## Current schemas

- `common/ErrorDetail`
- `common/SecretReference`
- `common/CapabilityDescriptor`
- `accounts/AccountDescriptor`
- `accounts/AccountCollection`
- `accounts/AccountMetadataUpdate`
- `credentials/CredentialDescriptor`
- `providers/ProviderDescriptor`
- `usage/UsageSnapshot`

Sessions and leases are deferred until their lifecycle semantics and owner are established.

## Security and privacy

General state carries secret references and safe credential metadata, never OAuth tokens, API keys, TOTP seeds, raw authentication files, decrypted vault content, or credential storage paths. Consumers must sanitize error messages before serialization. See [SECURITY.md](SECURITY.md) and [spec/security.md](spec/security.md).

Secret-free does not mean privacy-free. `displayName`, `endpoint`, account labels, and local metadata may identify a person or installation. Treat exchanged state as potentially sensitive. Repository examples are synthetic and use reserved `.invalid` endpoints.

## Transport and evolution

The schemas do not prescribe a transport. A future local JSON-RPC 2.0 mapping and UTF-8 NDJSON framing convention are documented in [spec/transport.md](spec/transport.md); neither is implemented here. Schema-major evolution is documented in [VERSIONING.md](VERSIONING.md).

## Canonical discovery

Use [`protocol-manifest.json`](protocol-manifest.json) to discover canonical schema IDs, paths, and SHA-256 digests. The v1 ID family is `urn:agent-state-protocol:v1:`.

## Provenance

The initial schemas were extracted from `MalenkiySolovey/codex-control-center` at source commit `47456c1754219344cf215108f7f3263f982cd691`, where Stage 2A introduced the staged contract. This repository is the canonical schema source; consuming applications may vendor an exact commit.
