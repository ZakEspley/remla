import inspect


def validate_device_arguments(device_name: str, cls: type, init_args: dict) -> None:
    parameters = inspect.signature(cls.__init__).parameters
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return

    unsupported = sorted(set(init_args) - set(parameters))
    if unsupported:
        controller_name = cls.__name__
        options = ", ".join(unsupported)
        raise TypeError(
            f"Device '{device_name}' uses controller '{controller_name}' but has "
            f"unsupported configuration options: {options}. Remove options that "
            "belong to a different controller."
        )
