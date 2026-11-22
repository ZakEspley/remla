import importlib
import unittest
from unittest import mock

from remla.labcontrol import Controllers
from remla.yaml import createDevicesFromYml, yaml


MOTOR_TYPES = (
    Controllers.StepperSimple,
    Controllers.StepperI2C,
    Controllers.FilterStepperI2C,
    Controllers.PololuStepperMotor,
    Controllers.S42CStepperMotor,
)
UNCONFIGURED = object()


class CyclicDeltaTests(unittest.TestCase):
    def delta(self, *args, **kwargs):
        module = importlib.import_module("remla.cyclic_motion")
        return module.shortest_cyclic_delta(*args, **kwargs)

    def test_shortest_path_wraps_in_both_directions(self):
        for current, target, expected in (
            (350, 10, 20),
            (10, 350, -20),
            (-10, 10, 20),
            (730, -10, -20),
            (10, 1090, 0),
        ):
            with self.subTest(current=current, target=target):
                self.assertEqual(self.delta(current, target, 360), expected)

    def test_half_cycle_tie_is_positive(self):
        self.assertEqual(self.delta(0, 180, 360), 180)
        self.assertEqual(self.delta(180, 0, 360), 180)
        self.assertEqual(self.delta(-180, 0, 360), 180)

    def test_bounds_select_longer_safe_path_instead_of_clipping(self):
        self.assertEqual(self.delta(10, 350, 360, lower=0, upper=360), 340)
        self.assertEqual(self.delta(350, 10, 360, lower=0, upper=360), -340)
        self.assertEqual(self.delta(180, 0, 360, lower=0, upper=180), -180)

    def test_one_sided_bounds_are_supported(self):
        self.assertEqual(self.delta(10, 350, 360, lower=0), 340)
        self.assertEqual(self.delta(350, 10, 360, upper=360), -340)

    def test_bounds_apply_to_accumulated_position_not_only_phase(self):
        self.assertEqual(self.delta(730, 350, 360, lower=720, upper=1100), 340)
        self.assertEqual(self.delta(720, 0, 360, lower=720, upper=720), 0)

    def test_no_safe_equivalent_target_is_rejected(self):
        with self.assertRaises(ValueError):
            self.delta(50, 200, 360, lower=0, upper=100)

    def test_current_outside_bounds_is_rejected_even_for_same_phase(self):
        for current in (-1, 101):
            with self.subTest(current=current):
                with self.assertRaises(ValueError):
                    self.delta(current, current, 360, lower=0, upper=100)

    def test_invalid_period_is_rejected(self):
        for period in (True, False, 0, -1, 3.5, "360", None):
            with self.subTest(period=period):
                with self.assertRaises((TypeError, ValueError)):
                    self.delta(0, 10, period)


class CyclicControllerTests(unittest.TestCase):
    def make_motor(
        self, controller_type, current=350, cyclic=None, bounds=(-2000, 2000),
        ref_points=None,
    ):
        if ref_points is None:
            ref_points = {"target": 10, "other": 350}
        bare = object.__new__(controller_type)
        bare.initParameters = {}
        bare.name = "Stage"
        bare.refPoints = ref_points
        bare.refPointsRaw = sorted(ref_points.values())
        bare.currentPosition = current
        bare.curPos = current
        bare.initialPosition = 0
        bare.homeSwitch = None
        bare.lowerBound, bare.upperBound = bounds
        bare.LB, bare.UB = bounds
        bare.state = {"position": current}

        def initialize(instance, *args, **kwargs):
            instance.__dict__.update(bare.__dict__)

            def move(steps):
                if controller_type is Controllers.S42CStepperMotor:
                    instance.curPos += steps
                    position = instance.curPos
                else:
                    instance.currentPosition += steps
                    position = instance.currentPosition
                instance.state["position"] = position
                return ("MESSAGE", f"Stage/position/{position}")

            instance.move = mock.Mock(side_effect=move)

        definition = {"type": controller_type.__name__, "refPoints": ref_points}
        if cyclic is not UNCONFIGURED:
            definition["cyclic"] = {"stepsPerCycle": 360} if cyclic is None else cyclic
        with mock.patch.object(controller_type, "__init__", new=initialize):
            return createDevicesFromYml({"Stage": definition})["Stage"]

    def test_yaml_opt_in_routes_all_supported_motors_across_zero(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type)
                motor.goto("target")
                motor.move.assert_called_once_with(20)
                self.assertEqual(motor.state["position"], 370)

    def test_cyclic_goto_preserves_accumulated_position_across_repeated_calls(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type)
                motor.goto("target")
                motor.goto("other")
                motor.goto("target")
                self.assertEqual(
                    motor.move.call_args_list, [mock.call(20), mock.call(-20), mock.call(20)]
                )
                position = (
                    motor.curPos if controller_type is Controllers.S42CStepperMotor
                    else motor.currentPosition
                )
                self.assertEqual(position, 370)
                self.assertEqual(motor.state["position"], 370)

    def test_half_cycle_tie_uses_positive_route_for_each_motor(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(
                    controller_type, current=180,
                    ref_points={"target": 0, "other": 180},
                )
                motor.goto("target")
                motor.move.assert_called_once_with(180)
                self.assertEqual(motor.state["position"], 360)

    def test_same_phase_does_not_change_accumulated_position(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type, current=730)
                motor.goto("target")
                motor.move.assert_not_called()
                self.assertEqual(motor.state["position"], 730)

    def test_unconfigured_motors_keep_linear_goto(self):
        for controller_type in MOTOR_TYPES:
            if controller_type is Controllers.FilterStepperI2C:
                continue
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type, cyclic=UNCONFIGURED)
                response = motor.goto("target")
                motor.move.assert_called_once_with(-340)
                self.assertEqual(motor.state["position"], 10)
                if controller_type in (Controllers.StepperSimple, Controllers.PololuStepperMotor):
                    self.assertIsNone(response, "Non-cyclic goto keeps its legacy reply shape")

    def test_unconfigured_filter_keeps_legacy_reference_spacing_and_wrap(self):
        motor = self.make_motor(
            Controllers.FilterStepperI2C, current=0, cyclic=UNCONFIGURED,
            ref_points={"zero": 0, "one": 100, "two": 200, "three": 300},
        )
        motor.goto("three")
        motor.move.assert_called_once_with(-100)
        self.assertEqual(motor.currentPosition, 300)

    def test_explicit_filter_uses_period_not_reference_spacing(self):
        motor = self.make_motor(
            Controllers.FilterStepperI2C, current=0,
            ref_points={"zero": 0, "one": 100, "two": 200, "three": 300},
        )
        motor.goto("three")
        motor.move.assert_called_once_with(-60)
        self.assertEqual(motor.currentPosition, -60)
        self.assertEqual(motor.state["position"], -60)

    def test_bounded_motors_choose_safe_long_route(self):
        for controller_type in MOTOR_TYPES[1:]:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type, bounds=(0, 360))
                motor.goto("target")
                motor.move.assert_called_once_with(-340)

    def test_bounded_motors_reject_unreachable_phase_without_moving(self):
        for controller_type in MOTOR_TYPES[1:]:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(
                    controller_type, current=50, bounds=(0, 100),
                    ref_points={"target": 200, "other": 50},
                )
                with self.assertRaises(ValueError):
                    motor.goto("target")
                motor.move.assert_not_called()
                self.assertEqual(motor.state["position"], 50)

    def test_rejected_goto_via_dispatch_does_not_invalidate_known_position(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(
                    controller_type, current=50, bounds=(0, 100),
                    ref_points={"blocked": 200, "valid": 60},
                )
                rejected = [("missing", KeyError)]
                if controller_type is not Controllers.StepperSimple:
                    rejected.append(("blocked", ValueError))
                for reference, error in rejected:
                    with self.assertRaises(error):
                        motor.cmdHandler("goto", [reference], "Stage")
                    motor.move.assert_not_called()
                motor.cmdHandler("goto", ["valid"], "Stage")
                motor.move.assert_called_once_with(10)
                self.assertEqual(motor.state["position"], 60)

    def test_relative_move_is_not_reduced_modulo_period(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type)
                motor.cmdHandler("move", ["720"], "Stage")
                motor.move.assert_called_once_with(720)
                self.assertEqual(motor.state["position"], 1070)

    def test_reset_keeps_absolute_return_to_initial_position(self):
        for controller_type in MOTOR_TYPES[1:]:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type, current=730, cyclic=UNCONFIGURED)
                motor.reset()
                motor.move.assert_called_once_with(-730)
                self.assertEqual(motor.state["position"], 0)

    def test_cyclic_reset_returns_to_starting_phase_without_unwinding_revolutions(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type, current=730)
                if controller_type is Controllers.StepperSimple:
                    motor.initialPosition = 0
                motor.reset()
                motor.move.assert_called_once_with(-10)
                self.assertEqual(motor.state["position"], 720)

    def test_six_slot_filter_reset_uses_one_slot_not_five(self):
        motor = self.make_motor(
            Controllers.FilterStepperI2C, current=-1350,
            cyclic={"stepsPerCycle": 1620}, bounds=(-1_000_000, 1_000_000),
            ref_points={f"{angle}deg": -(angle // 60) * 270 for angle in range(0, 360, 60)},
        )
        motor.reset()
        motor.move.assert_called_once_with(-270)
        self.assertEqual(motor.state["position"], -1620)
        motor.move.reset_mock()
        motor.goto("0deg")
        motor.move.assert_not_called()

    def test_six_slot_filter_moves_one_slot_in_both_directions(self):
        refs = {f"{angle}deg": -(angle // 60) * 270 for angle in range(0, 360, 60)}
        motor = self.make_motor(
            Controllers.FilterStepperI2C, current=0,
            cyclic={"stepsPerCycle": 1620}, bounds=(-1_000_000, 1_000_000),
            ref_points=refs,
        )
        for reference, steps in (
            ("60deg", -270), ("0deg", 270),
            ("300deg", 270), ("0deg", -270),
        ):
            with self.subTest(reference=reference):
                motor.move.reset_mock()
                motor.cmdHandler("goto", [reference], "Stage")
                motor.move.assert_called_once_with(steps)
                self.assertEqual(motor.state["position"] % 1620, refs[reference] % 1620)

    def test_failed_motion_invalidates_phase_for_later_cyclic_goto(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type)
                motor.move.side_effect = RuntimeError("motion interrupted")
                with self.assertRaisesRegex(RuntimeError, "motion interrupted"):
                    motor.goto("target")
                motor.move.reset_mock()
                with self.assertRaisesRegex(ValueError, "position|phase"):
                    motor.goto("target")
                motor.move.assert_not_called()

    def test_safe_stop_invalidates_phase_for_later_cyclic_goto(self):
        for controller_type in MOTOR_TYPES:
            with self.subTest(controller=controller_type.__name__):
                motor = self.make_motor(controller_type)
                motor.device = mock.Mock()
                motor.release = mock.Mock()
                motor.pi = mock.Mock()
                motor.enablePin = 1
                motor.EN = 2
                with mock.patch.object(Controllers, "pi", mock.Mock()):
                    motor.safe_stop()
                with self.assertRaisesRegex(ValueError, "position|phase"):
                    motor.goto("target")
                motor.move.assert_not_called()


class CyclicYamlValidationTests(unittest.TestCase):
    def assert_rejected_before_constructor(self, controller_type, cyclic):
        definition = {"type": controller_type.__name__, "cyclic": cyclic}
        with mock.patch.object(controller_type, "__init__", return_value=None) as constructor:
            with self.assertRaisesRegex((TypeError, ValueError), "cyclic|stepsPerCycle"):
                createDevicesFromYml({"Stage": definition})
            constructor.assert_not_called()

    def test_yaml_mapping_is_accepted_without_hardware_initialization(self):
        definition = yaml.load(
            "Stage:\n  type: StepperI2C\n  cyclic: {stepsPerCycle: 360}\n"
        )["Stage"]
        motor = CyclicControllerTests().make_motor(
            Controllers.StepperI2C, cyclic=definition["cyclic"]
        )
        motor.goto("target")
        motor.move.assert_called_once_with(20)

    def test_invalid_cyclic_options_are_rejected_before_any_motor_constructor(self):
        invalid = (
            True, False, 360, "360", [], {},
            {"stepsPerCycle": True}, {"stepsPerCycle": False},
            {"stepsPerCycle": 0}, {"stepsPerCycle": -360},
            {"stepsPerCycle": 360.0}, {"stepsPerCycle": "360"},
            {"stepsPerCycle": None},
            {"stepsPerCycle": 360, "unexpected": 1},
        )
        for controller_type in MOTOR_TYPES:
            for cyclic in invalid:
                with self.subTest(controller=controller_type.__name__, cyclic=cyclic):
                    self.assert_rejected_before_constructor(controller_type, cyclic)

    def test_nonmotor_rejects_cyclic_before_constructor(self):
        self.assert_rejected_before_constructor(
            Controllers.PowerConsumer, {"stepsPerCycle": 360}
        )

    def test_dc_motors_reject_cyclic_until_measured_phase_and_goto_exist(self):
        for controller_type in (Controllers.DCMotorI2C, Controllers.PololuDCMotor):
            with self.subTest(controller=controller_type.__name__):
                self.assert_rejected_before_constructor(
                    controller_type, {"stepsPerCycle": 360}
                )

    def test_invalid_later_cycle_is_rejected_before_earlier_motor_initializes(self):
        devices = {
            "First": {"type": "S42CStepperMotor", "EN": 2, "STEP": 3, "DIR": 4,
                      "bounds": [0, 360]},
            "Later": {"type": "StepperI2C", "cyclic": {"stepsPerCycle": 0}},
        }
        with mock.patch.object(Controllers.S42CStepperMotor, "__init__", return_value=None) as first:
            with self.assertRaisesRegex(ValueError, "stepsPerCycle"):
                createDevicesFromYml(devices)
            first.assert_not_called()

    def test_initial_position_must_fit_cyclic_travel_bounds_before_constructor(self):
        for controller_type, config in (
            (Controllers.StepperI2C, {"initialPosition": 500, "bounds": [0, 360]}),
            (Controllers.StepperI2C, {"bounds": [10, 360]}),
            (Controllers.PololuStepperMotor, {"bounds": [10, 360]}),
            (Controllers.S42CStepperMotor, {"bounds": [10, 360]}),
        ):
            with self.subTest(controller=controller_type.__name__, config=config):
                definition = {"type": controller_type.__name__, "refPoints": {"home": 0},
                              "cyclic": {"stepsPerCycle": 360}, **config}
                with mock.patch.object(controller_type, "__init__", return_value=None) as constructor:
                    with self.assertRaisesRegex(ValueError, "initialPosition|initial position"):
                        createDevicesFromYml({"Stage": definition})
                    constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
