from __future__ import annotations

import unittest

from upper_computer.gas_calibration import (
    MQ135_CLEAN_AIR_PPM,
    calculate_gas_ppm,
    calibrate_r0_from_clean_air_raw,
)
from upper_computer.data_parser import parse_gateway_frame


class GasCalibrationTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()