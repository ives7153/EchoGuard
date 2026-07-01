from __future__ import annotations

import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication

from upper_computer.core.data_manager import DataManager, NodeState
from upper_computer.gas_calibration import (
    MQ135_CLEAN_AIR_PPM,
    calculate_gas_ppm,
    calibrate_r0_from_clean_air_raw,
)
from upper_computer.data_parser import parse_gateway_frame


class GasCalibrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._qt_app = QCoreApplication.instance() or QCoreApplication([])

    def test_ppm_increases_with_raw_adc(self) -> None:
        r0 = calibrate_r0_from_clean_air_raw(1000.0)
        low = calculate_gas_ppm(800.0, r0)
        high = calculate_gas_ppm(1400.0, r0)
        self.assertGreater(high, low)

    def test_invalid_raw_is_safe(self) -> None:
        self.assertEqual(calculate_gas_ppm(0), 0.0)
        self.assertEqual(calculate_gas_ppm(-1), 0.0)
        self.assertEqual(calculate_gas_ppm("bad"), 0.0)

    def test_clean_air_calibration_returns_positive_r0(self) -> None:
        r0 = calibrate_r0_from_clean_air_raw(1000.0, MQ135_CLEAN_AIR_PPM)
        self.assertGreater(r0, 0.0)
        ppm = calculate_gas_ppm(1000.0, r0)
        self.assertAlmostEqual(ppm, MQ135_CLEAN_AIR_PPM, delta=0.5)

    def test_parser_preserves_raw_and_adds_ppm(self) -> None:
        frame = parse_gateway_frame('{"id":1,"seq":2,"gas":1000,"temp":25.0,"hum":50,"rssi":-60}')
        self.assertTrue(frame["valid"])
        self.assertEqual(frame["gas_raw"], 1000.0)
        self.assertGreater(frame["gas_ppm"], 0.0)
        self.assertEqual(frame["gas"], frame["gas_ppm"])

    def test_data_manager_uses_legacy_global_r0_as_fallback(self) -> None:
        global_r0 = calibrate_r0_from_clean_air_raw(900.0)
        with patch("upper_computer.core.data_manager.load_ui_settings", return_value={"mq135_r0_kohm": global_r0}):
            manager = DataManager()

        sample = manager._apply_gas_calibration({"node_id": 9, "gas_raw": 1100.0})

        self.assertAlmostEqual(sample["gas_ppm"], calculate_gas_ppm(1100.0, global_r0))

    def test_data_manager_prefers_node_specific_r0(self) -> None:
        node1_r0 = calibrate_r0_from_clean_air_raw(900.0)
        node2_r0 = calibrate_r0_from_clean_air_raw(1300.0)
        settings = {
            "mq135_r0_kohm": calibrate_r0_from_clean_air_raw(1000.0),
            "mq135_node_r0_kohm": {"1": node1_r0, "2": node2_r0},
        }
        with patch("upper_computer.core.data_manager.load_ui_settings", return_value=settings):
            manager = DataManager()

        node1 = manager._apply_gas_calibration({"node_id": 1, "gas_raw": 1100.0})
        node2 = manager._apply_gas_calibration({"node_id": 2, "gas_raw": 1100.0})

        self.assertAlmostEqual(node1["gas_ppm"], calculate_gas_ppm(1100.0, node1_r0))
        self.assertAlmostEqual(node2["gas_ppm"], calculate_gas_ppm(1100.0, node2_r0))
        self.assertNotAlmostEqual(node1["gas_ppm"], node2["gas_ppm"])

    def test_current_node_calibration_updates_only_active_node(self) -> None:
        old_node2_r0 = calibrate_r0_from_clean_air_raw(1200.0)
        settings = {"mq135_node_r0_kohm": {"2": old_node2_r0}}
        with (
            patch("upper_computer.core.data_manager.load_ui_settings", return_value=settings),
            patch("upper_computer.core.data_manager.save_ui_settings") as save_settings,
        ):
            manager = DataManager()
            manager.nodes[1] = NodeState(node_id=1, label="node1", online=True)
            manager.nodes[2] = NodeState(node_id=2, label="node2", online=True)
            manager._active_node = 1
            manager.history = [
                {"node_id": 2, "gas_raw": 1200.0},
                {"node_id": 1, "gas_raw": 950.0},
            ]

            manager.calibrate_mq135_clean_air()

        self.assertIn(1, manager.gas_node_calibration_r0)
        self.assertAlmostEqual(manager.gas_node_calibration_r0[1], calibrate_r0_from_clean_air_raw(950.0))
        self.assertAlmostEqual(manager.gas_node_calibration_r0[2], old_node2_r0)
        saved = save_settings.call_args.args[0]["mq135_node_r0_kohm"]
        self.assertIn("1", saved)
        self.assertIn("2", saved)

    def test_all_online_calibration_updates_each_online_node(self) -> None:
        old_node3_r0 = calibrate_r0_from_clean_air_raw(1600.0)
        settings = {"mq135_node_r0_kohm": {"3": old_node3_r0}}
        with (
            patch("upper_computer.core.data_manager.load_ui_settings", return_value=settings),
            patch("upper_computer.core.data_manager.save_ui_settings") as save_settings,
        ):
            manager = DataManager()
            manager.nodes[1] = NodeState(node_id=1, label="node1", online=True)
            manager.nodes[2] = NodeState(node_id=2, label="node2", online=True)
            manager.nodes[3] = NodeState(node_id=3, label="node3", online=False)
            manager.history = [
                {"node_id": 1, "gas_raw": 900.0},
                {"node_id": 2, "gas_raw": 1300.0},
                {"node_id": 3, "gas_raw": 1600.0},
            ]

            manager.calibrate_all_mq135_clean_air()

        self.assertAlmostEqual(manager.gas_node_calibration_r0[1], calibrate_r0_from_clean_air_raw(900.0))
        self.assertAlmostEqual(manager.gas_node_calibration_r0[2], calibrate_r0_from_clean_air_raw(1300.0))
        self.assertAlmostEqual(manager.gas_node_calibration_r0[3], old_node3_r0)
        saved = save_settings.call_args.args[0]["mq135_node_r0_kohm"]
        self.assertIn("1", saved)
        self.assertIn("2", saved)
        self.assertIn("3", saved)


if __name__ == "__main__":
    unittest.main()
