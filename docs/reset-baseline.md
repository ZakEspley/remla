# Reset baseline

When the active WebSocket owner disconnects with no waiting user, ReMLA drains
the owner's work and calls `reset()` on every configured device. If a user is
waiting, ReMLA changes no hardware state until that user chooses reset or
continue; the pending handoff resets automatically after 60 seconds. If the
pending handoff user disconnects and no users remain, ReMLA also resets.

The baseline is currently defined by each controller's reset contract and its
lab YAML constructor settings:

- `PDUOutlet` turns every configured outlet off.
- `PowerConsumer` turns its configured provider route off.
- `SingleGPIO` drives its output low.
- `StepperI2C` returns to YAML `initialPosition` (default `0`) and releases
  its coils.
- `ArduCamMultiCamera` returns to YAML `initialCamera` and applies its default
  camera settings.

Stepper position is not an absolute mechanical home: it is tracked from the
configured `initialPosition` after ReMLA starts. Labs requiring a known
physical zero must provide and use a homing procedure before operation. A
future per-lab baseline schema should declare homing and device-specific target
states explicitly.
