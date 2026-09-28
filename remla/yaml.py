from collections import defaultdict
import os
import re
from pathlib import Path, PosixPath, PurePosixPath, PurePath
from typing import Any, List

import typer
from ruamel.yaml import YAML
from ruamel.yaml.nodes import ScalarNode

from remla.device_config import validate_device_arguments
from remla.labcontrol import Controllers


# Initialize the YAML parser
yaml = YAML(typ='safe')
# yaml.preserve_quotes = True  # Preserve quotes style
yaml.indent(mapping=2, sequence=4, offset=2)  # Set indentation, optional
yaml.default_flow_style = False

ENVIRONMENT_REFERENCE = re.compile(r"^\$\{(REMLA_[A-Z0-9_]+)\}$")


def resolve_environment_reference(value, device_name, option_name):
    if not isinstance(value, str):
        return value
    match = ENVIRONMENT_REFERENCE.fullmatch(value)
    if match is None:
        return value
    variable_name = match.group(1)
    resolved = os.environ.get(variable_name)
    if resolved is None:
        raise ValueError(
            f"Device '{device_name}' requires environment variable '{variable_name}' "
            f"for option '{option_name}'"
        )
    return resolved
# yaml.allow_unicode = True

# Used to convert pathLib paths too yml files and vice versa.
def path_representer(dumper, data):
    return dumper.represent_scalar('!path', str(data))

def path_constructor(loader, node):
    value = loader.construct_scalar(node)
    return Path(value)

# Add the custom representer for Path objects
for cls in [Path, PosixPath, PurePosixPath, PurePath]:
    yaml.representer.add_representer(cls, path_representer)
# Add the custom constructor for Path objects
yaml.constructor.add_constructor('!path', path_constructor)


def createDevicesFromYml(deviceData:dict) -> dict[Any]:
    """
    Create and initialize devices from a YAML configuration file.

    This function reads a YAML file that defines devices and their properties,
    including dependencies on other devices. It ensures all devices are initialized
    in the correct order, even when some devices depend on others being created first.

    :param deviceDict: Dictionary of device names and properties read directly from the yaml file.
    :type deviceDict: dict
    :return: A list of initialized device objects.
    :rtype: List[Any]
    :raises ValueError: If there is a circular dependency detected among devices.
    """

    # Dictionary to hold name -> object mapping
    devices = {}

    # Set to track objects currently being initialized to detect circular dependencies
    inProgress = set()

    def resolveDependencies(deviceName):
        typer.echo(f"Resolving dependency for {deviceName}")
        """
        Recursively initialize a device and its dependencies.

        This internal function creates a device object by its name after resolving
        all necessary dependencies specified in the configuration. It supports
        recursive resolution to handle nested dependencies.

        :param deviceName: The name of the device to initialize.
        :type deviceName: str
        :return: An initialized device object.
        :rtype: Any
        :raises ValueError: If circular dependencies are detected.
        """
        # Check if device is already created and return it
        if deviceName in devices:
            return devices[deviceName]

        # Circular dependency check
        if deviceName in inProgress:
            raise ValueError(f"Circular dependency detected involving {deviceName}")

        # Mark this device as being in the process of initialization
        inProgress.add(deviceName)

        # Retrieve the class type and initialization arguments for this device
        deviceDetails = deviceData[deviceName]

        # cls = globals()[deviceDetails['type']]
        cls = getattr(Controllers, deviceDetails['type'])
        power_config = deviceDetails.get("power")
        initArgs = {
            key: resolve_environment_reference(value, deviceName, key)
            for key, value in deviceDetails.items()
            if key not in ['type', 'name', 'power']
        }
        validate_device_arguments(deviceName, cls, initArgs)

        # Resolve dependencies for each initialization argument
        for arg, value in initArgs.items():
            if isinstance(value, str) and value in deviceData:
                initArgs[arg] = resolveDependencies(value)

        provider = None
        target = None
        if power_config is not None:
            if not isinstance(power_config, dict):
                raise TypeError(f"Device '{deviceName}' power configuration must be an object")
            provider_name = power_config.get("provider")
            target = power_config.get("outlet")
            if not isinstance(provider_name, str) or target is None:
                raise TypeError(f"Device '{deviceName}' power configuration requires provider and outlet")
            if provider_name not in deviceData:
                raise ValueError(f"Device '{deviceName}' references unknown power provider '{provider_name}'")
            provider = resolveDependencies(provider_name)
            if hasattr(provider, "resolve_power_target"):
                provider.resolve_power_target(target)
            if not callable(getattr(provider, "get_power_state", None)) or not callable(
                getattr(provider, "set_power_state", None)
            ):
                raise TypeError(f"Power provider '{provider_name}' does not support power routing")

        # Create the device instance and add to the devices dictionary
        device = cls(name=deviceName, **initArgs)
        if power_config is not None:
            device.configure_power_route(provider, target)
        devices[deviceName] = device

        # Remove device from inProgress set
        inProgress.remove(deviceName)

        return device

    # Initialize all devices by resolving their dependencies
    for name in deviceData.keys():
        if name not in devices:
            resolveDependencies(name)

    return devices
