# Routed power controls

`PowerConsumer` represents a named lab target whose binary power is supplied by
another configured device. It has no hardware driver of its own.

```yaml
Laser:
  type: PowerConsumer
  power:
    provider: ASDIpdu
    outlet: Laser
```

Consumers provide `power_on`, `power_off`, and `power_toggle`. Toggle reads the
provider's current state on the server and switches it to the opposite state.
Use explicit on/off when the desired state is known.

Providers implement `get_power_state` and `set_power_state`. A provider and
every routed consumer must share one named lock group. ReMLA rejects invalid
providers, targets, and lock assignments during startup.

`PDUOutlet` supports `apiMode: rest` for DLI controllers with the REST-style
API enabled. REST mode uses HTTP Digest authentication, reads each outlet's
physical state, maps ReMLA outlet numbers to DLI's zero-based indexes, and uses
one all-off request during reset. Keep `apiMode: legacy` until REST mode is
validated for a lab.

`PDUOutlet` refreshes its outlet status from the DLI provider before a toggle.
If that read is unavailable or unknown, the toggle fails rather than guessing.

Providers own the physical baseline reset. `PowerConsumer.reset()` and
`safe_stop()` only clear their cached state, avoiding duplicate provider requests
during a lab reset. Direct provider commands remain available for legacy and diagnostic use, but
clients should command the named consumer instead of provider topology.
