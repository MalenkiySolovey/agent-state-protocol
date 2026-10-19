# Schema versioning

`schemaVersion` is the major version of an individual message contract. It is independent of repository commits and any future repository release numbering. The current family is `schemaVersion: 1`; this repository does not publish a stable package or release as part of its initial extraction.

## Compatible v1 changes

- Add an optional field without changing the meaning of existing fields.
- Add an independent schema.
- Add controlled scalar values to the documented `CapabilityDescriptor.extensions` map.
- Add an enum value only where consumers follow the unknown-value tolerance rule below.

## Breaking changes

The following require a new schema major family (for example, v2):

- Remove or rename a field.
- Change requiredness incompatibly.
- Change a field's type or semantic meaning.
- Change the meaning of an existing schema identifier.

Existing v1 semantics must not change silently.

## Unknown enum values

Schemas enumerate values known to this version. Consumers must not crash when they encounter an unknown semantic value; they should preserve it where practical or treat it as unsupported/unknown. An enum addition is compatible only for consumers that honor this rule. JSON Schema enum validation by itself does not make generated clients forward-compatible.
