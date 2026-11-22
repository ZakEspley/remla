"""Position planning for motors explicitly configured for cyclic travel."""


def parse_cyclic_period(config):
    if not isinstance(config, dict) or set(config) != {"stepsPerCycle"}:
        raise ValueError("cyclic requires only stepsPerCycle")
    period = config["stepsPerCycle"]
    if type(period) is not int or period <= 0:
        raise ValueError("cyclic stepsPerCycle must be a positive integer")
    return period


def shortest_cyclic_delta(current, target, period, lower=None, upper=None):
    """Return a signed step count to a target phase without crossing bounds.

    At exactly half a cycle, the positive route wins. Bounds are physical
    accumulated-position limits, not phase endpoints; never silently clamp.
    """
    if any(type(value) is not int for value in (current, target, period)) or period <= 0:
        raise ValueError("Cyclic positions and period must be integer steps")
    if ((lower is not None and current < lower)
            or (upper is not None and current > upper)
            or (lower is not None and upper is not None and lower > upper)):
        raise ValueError("Current position is outside cyclic travel bounds")

    forward = (target - current) % period
    candidates = (forward, forward - period) if forward else (0,)
    for delta in sorted(candidates, key=lambda value: (abs(value), value < 0)):
        endpoint = current + delta
        if (lower is None or endpoint >= lower) and (upper is None or endpoint <= upper):
            return delta
    raise ValueError("No cyclic route fits the configured travel bounds")
