import importlib
import unittest
from unittest import mock


controllers = importlib.import_module("remla.labcontrol.Controllers")


class ControllerSafeStopTests(unittest.TestCase):
    def test_configured_power_route_delegates_on_off_and_toggle(self):
        class Consumer(controllers.BaseController):
            deviceType = "controller"

            def reset(self):
                pass

            def safe_stop(self):
                pass

        provider = mock.Mock()
        provider.get_power_state.return_value = "off"
        consumer = Consumer("Instrument")
        consumer.configure_power_route(provider, "instrument")

        consumer.power_on([""])
        consumer.power_off([])
        consumer.power_toggle([])

        self.assertEqual(
            provider.set_power_state.call_args_list,
            [mock.call("instrument", "on"), mock.call("instrument", "off"), mock.call("instrument", "on")],
        )
    def test_every_concrete_controller_declares_safe_stop(self):
        controller_types = [
            controllers.PDUOutlet,
            controllers.Plug,
            controllers.StepperSimple,
            controllers.DCMotorI2C,
            controllers.StepperI2C,
            controllers.FilterStepperI2C,
            controllers.AbsorberController,
            controllers.Multiplexer,
            controllers.Keithley6514Electrometer,
            controllers.Keithley2000Multimeter,
            controllers.PololuStepperMotor,
            controllers.PololuDCMotor,
            controllers.ArduCamMultiCamera,
            controllers.PiCamera2MultiCam,
            controllers.ElectronicScreen,
            controllers.LimitSwitch,
            controllers.HomeSwitch,
            controllers.SingleGPIO,
            controllers.PushButton,
            controllers.PWMChannel,
            controllers.S42CStepperMotor,
            controllers.FS5103RContinuousMotor,
            controllers.GeneralPWMServo,
        ]

        self.assertTrue(getattr(controllers.BaseController.safe_stop, "__isabstractmethod__"))
        for controller_type in controller_types:
            self.assertIn("safe_stop", controller_type.__dict__)
            self.assertFalse(controller_type.__abstractmethods__)

    def test_i2c_dc_motor_stops_throttle(self):
        controller = object.__new__(controllers.DCMotorI2C)
        controller.device = mock.Mock()

        controller.safe_stop()

        self.assertEqual(controller.device.throttle, 0)

    def test_pololu_dc_motor_disables_output(self):
        controller = object.__new__(controllers.PololuDCMotor)
        controller.initParameters = {}
        controller.throttle = mock.Mock()
        controller.notEnablePin = 12
        pi = mock.Mock()

        with mock.patch.object(controllers, "pi", pi):
            controller.safe_stop()

        controller.throttle.assert_called_once_with(0)
        pi.write.assert_called_once_with(12, 1)

    def test_continuous_motor_disables_pwm(self):
        controller = object.__new__(controllers.FS5103RContinuousMotor)
        controller.disable = mock.Mock()

        controller.safe_stop()

        controller.disable.assert_called_once_with()

    def test_servo_disables_pwm(self):
        controller = object.__new__(controllers.GeneralPWMServo)
        controller.disable = mock.Mock()

        controller.safe_stop()

        controller.disable.assert_called_once_with()

    def test_camera_safe_stop_closes_resources(self):
        controller = object.__new__(controllers.PiCamera2MultiCam)
        controller.close = mock.Mock()

        controller.safe_stop()

        controller.close.assert_called_once_with()

    def test_arducam_reset_logs_its_configured_camera(self):
        controller = object.__new__(controllers.ArduCamMultiCamera)
        controller.initParameters = {}
        controller.name = "Camera"
        controller.initialCamera = "a"
        controller.defaultSettings = None
        controller.camera = mock.Mock()

        with mock.patch.object(controllers, "logging") as logging:
            controller.reset()

        controller.camera.assert_called_once_with("a")
        logging.info.assert_called_once_with(
            "Resetting camera %s to initial camera %s", "Camera", "a"
        )


if __name__ == "__main__":
    unittest.main()
