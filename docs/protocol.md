# Runtime Protocol

## Status

This defines the version 1 JSON event schema. WebSocket delivery remains on the legacy text protocol until a client opts into a later implementation; this document does not change live WebSocket frames.

## Event envelope

Every JSON event uses this envelope:

```json
{
  "version": 1,
  "type": "operation.started",
  "timestamp": "2026-09-20T12:00:00Z",
  "payload": {}
}
```

- `version` is the protocol schema version.
- `type` is one of the event names below.
- `timestamp` is an RFC 3339 UTC timestamp.
- `payload` contains only fields defined for that event type.

## State events

`state.snapshot` contains the complete current view after connection or recovery:

```json
{
  "lifecycle": "ready",
  "control": {"state": "active"},
  "operations": []
}
```

`state.changed` contains the changed lifecycle, control, or device-state fields. The payload always includes `lifecycle` and may include `control`, `devices`, and `last_fault`.

Lifecycle values are `starting`, `ready`, `resetting`, `stopping`, `stopped`, and `faulted`.

## Operation events

`operation.queued`, `operation.started`, `operation.completed`, and `operation.failed` include:

```json
{
  "operation_id": "uuid",
  "device": "camera",
  "method": "camera",
  "lock_group": "camera",
  "status": "started"
}
```

Completed events add `result`; failed events add a stable `error` code and an operator-safe message. Timed-out operations use `operation.failed` with `error: "timed_out"` and leave the lifecycle `faulted`.

## Reset and fault events

- `reset.started` includes `reason` (`handoff`, `recovery`, or `shutdown`).
- `reset.completed` includes `reason` and `success`.
- `fault` includes `code`, `message`, and the active lifecycle state.

## Compatibility

Legacy slash-delimited requests and `MESSAGE:`, `ALERT:`, and `COMMAND:` responses remain unchanged during the compatibility period. A WebSocket connection must use either legacy frames or versioned JSON frames, never a mixture.

## Local recovery IPC

`remla recover` sends a local Unix-socket command such as `recover/reset`, `recover/resume`, or `recover/shutdown`. The running service replies with JSON:

```json
{"ok": true, "state": "ready"}
```

Failure replies use `{"ok": false, "error": "operations_running"}`. IPC recovery is local-only and does not change the WebSocket protocol.
