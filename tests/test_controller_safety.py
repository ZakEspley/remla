import importlib
import unittest
from unittest import mock


controllers = importlib.import_module("remla.labcontrol.Controllers")


class ControllerSafeStopTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
