# Future transport mapping (not implemented)

The schemas are transport-neutral. This document records a possible local mapping to JSON-RPC 2.0; it does not define or implement a server, client, socket, named pipe, or daemon.

## JSON-RPC 2.0 messages

- A request contains `jsonrpc: "2.0"`, a stable `method`, optional `params`, and an `id` when a response is expected.
- A response contains `jsonrpc: "2.0"`, the matching `id`, and exactly one of `result` or `error`.
- A notification omits `id` and receives no response.
- Method names beginning with `rpc.` are reserved.

Keep transport errors distinct from application errors. A JSON-RPC error uses its required integer `error.code`; an application `ErrorDetail` may be carried in `error.data` with its own string `errorCode`.

## Local stream framing convention

If a future local stream transport is introduced, frame UTF-8 JSON-RPC messages as NDJSON: one complete compact JSON text per line, terminated by LF. A parser may tolerate CRLF. Do not pretty-print multi-line messages on the wire.

No transport implementation is part of this repository.
