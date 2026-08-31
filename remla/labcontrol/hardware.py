from dataclasses import dataclass
from importlib import import_module


class DeferredHardwareModule:
    def __init__(self, name, constants=None):
        self.name = name
        self.constants = constants or {}
        self.module = None

    def bind(self, module):
        self.module = module

    def __getattr__(self, name):
        if self.module is not None:
            return getattr(self.module, name)
        if name in self.constants:
            return self.constants[name]
        raise RuntimeError(f"{self.name} is not initialized")


class HardwareResourceProxy:
    def __init__(self, attribute):
        self.attribute = attribute

    def __getattr__(self, name):
        return getattr(getattr(get_hardware_resources(), self.attribute), name)


@dataclass
class HardwareResources:
    pi: object
    gpio: object
    visa_manager: object


gpio = DeferredHardwareModule(
    "RPi.GPIO",
    {
        "BCM": 11,
        "HIGH": 1,
        "LOW": 0,
        "IN": 1,
        "OUT": 0,
        "PUD_DOWN": 21,
        "PUD_UP": 22,
        "RISING": 31,
        "FALLING": 32,
    },
)
pigpio = DeferredHardwareModule("pigpio")
pi = HardwareResourceProxy("pi")
visaManager = HardwareResourceProxy("visa_manager")
_hardware_resources = None


def initialize_hardware_resources() -> HardwareResources:
    global _hardware_resources

    if _hardware_resources is None:
        pigpio_module = import_module("pigpio")
        gpio_module = import_module("RPi.GPIO")
        visa_module = import_module("pyvisa")
        pi_instance = pigpio_module.pi()
        gpio_module.setmode(gpio_module.BCM)
        visa_manager = visa_module.ResourceManager("@py")
        pigpio.bind(pigpio_module)
        gpio.bind(gpio_module)
        _hardware_resources = HardwareResources(
            pi=pi_instance,
            gpio=gpio_module,
            visa_manager=visa_manager,
        )

    return _hardware_resources


def get_hardware_resources() -> HardwareResources:
    if _hardware_resources is None:
        raise RuntimeError("Hardware resources are not initialized")
    return _hardware_resources
