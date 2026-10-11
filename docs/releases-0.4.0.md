# ReMLA 0.4.0

## Highlights

- Adds provider-routed `PowerConsumer` controls, DLI REST support, named runtime
  secrets, and scoped shared-PDU reset behavior.
- Adds negotiated JSON WebSocket v1, state/queue events, and a copyable JSON
  browser client.
- Improves owner-disconnect draining, handoff safety, foreground logging, and
  service restart operations.

## Upgrade notes

- Migrate passwords to `${secret:name}` references managed with `sudo remla
  secrets` before removing legacy credential values.
- Shared PDU labs must configure the provider's `outlets` list to include only
  outlets owned by that lab before using REST reset behavior.
- Legacy browser clients remain supported. JSON-state UI adoption is optional.
