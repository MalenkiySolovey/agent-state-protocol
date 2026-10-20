# Security and privacy considerations

The schemas intentionally model secret references and credential state rather than secret material. They do not define credential acquisition, vault storage, encryption, access control, or secure transport.

Consumers must sanitize `ErrorDetail` messages and detail values before encoding them. A valid JSON string may still contain a token, key, or other sensitive value; JSON Schema cannot prove that arbitrary text is safe.

Fields such as `displayName`, `baseEndpoint`, `accountId`, provider identifiers, and user-selected labels may contain identifying or installation-specific information even when they contain no credential. Treat exchanged state as potentially sensitive and apply the consumer's own privacy and retention rules.

`AccountNicknameState.nickname` is an explicit user-selected label and may contain `@`; it is not an email claim. `safeFallbackDisplayName` is a redacted non-email projection, not a field for retaining an email-derived fallback or identity hidden by a nickname. A non-null nickname uses the generic `Account` fallback. Exact nickname absence is represented by `null`, not by an empty string.

All examples in this repository are synthetic. Real account data, provider configurations, endpoints, paths, and credentials do not belong in schemas, examples, tests, or issue reports.
