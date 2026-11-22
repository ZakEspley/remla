# Opt-in cyclic stepper travel

For a stepper that is physically safe to rotate continuously in either direction,
add `cyclic` to **that motor** in lab YAML. Its value is the number of commanded
steps in one full revolution, including configured microstepping and gearing:

```yaml
devices:
  Wheel:
    type: StepperI2C
    terminal: 1
    bounds: [-3200, 3200]
    refPoints: {start: 0, quarter: 400}
    initialPosition: 0
    cyclic: {stepsPerCycle: 1600}
```

This is an example, **not** a photo1 configuration or evidence that a real wheel
has these bounds or step count. Verify wiring, direction, range, cycle length,
reference phase, and mechanical freedom on the actual motor before enabling it.
Without `cyclic`, the motor keeps its previous linear `goto` behavior. An
invalid/empty cyclic mapping or unsupported device fails setup rather than
silently enabling motion with a guessed period.

For an opted-in stepper, `goto` targets an existing named `refPoints` step
phase. ReMLA considers both routes to that phase, chooses the shorter route
whose **entire travel** remains within accumulated-position bounds, and
chooses the positive direction on an equal-distance tie. If neither route
fits, it refuses the command; it does not clamp a cyclic target to a bound.
`move`, admin commands, and `safe_stop` retain their existing semantics. An
opted-in `reset` returns to the configured starting **phase** by the shortest
safe route rather than unwinding every accumulated revolution; without the
opt-in, reset still returns to its original absolute baseline. Position state
remains accumulated steps (so a cyclic reset may report a whole-cycle multiple
instead of zero), not a number wrapped to the cycle.
If a cyclic motion raises or the controller is safe-stopped, its phase is
considered untrusted and later cyclic `goto` commands are refused. A restart
clears the in-memory fault but does **not** establish a physical reference:
verify the motor's actual phase against the configured starting position under
operator supervision before using cyclic `goto` again. Do not infer recovery
from a cached position or a normal relative move.

`StepperSimple`, `StepperI2C`, `FilterStepperI2C`, `PololuStepperMotor`, and
`S42CStepperMotor` can use this opt-in routing. The older filter subclass keeps
its original behavior when `cyclic` is absent; do not infer a period from the
spacing of its references for new opt-ins. Configurations with limit/home
switches are rejected for this first implementation; position references must
be integer steps, and configured bounds must be whole-step endpoints. These
checks cannot prove a motor is physically safe to turn: startup position and
missed steps can still make software position inaccurate. Do not publish a
hardware release before operator-supervised validation and fault recovery.

`DCMotorI2C` and `PololuDCMotor` currently accept throttle commands but have
no measured phase or positional `goto`. A `cyclic` setting on these controllers
is rejected before hardware initialization; positional DC support requires a
reviewed encoder/position source first. Continuous-rotation servos are out of
scope. Photo1 has two filter-wheel opt-ins in an isolated test runtime; their
physical period and travel time still need operator-supervised measurement.
