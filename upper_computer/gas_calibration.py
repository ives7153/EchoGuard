"""MQ-135 ADC raw value to estimated CO2 ppm conversion helpers.

The firmware keeps the wire protocol small and sends only the ESP32 ADC raw value.
The upper computer applies the hardware divider and MQ-135 curve parameters here.
The result is an estimate for rescue-scene situational awareness, not a metrology value.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pow
from typing import Any

MQ135_VCC = 5.0
MQ135_RL_KOHM = 10.0
ESP32_ADC_MAX_MV = 3300.0
ESP32_ADC_MAX_RAW = 4095.0
MQ135_DIVIDER_TOP_KOHM = 10.0
MQ135_DIVIDER_BOTTOM_KOHM = 20.0
MQ135_CO2_A = 116.6020682
MQ135_CO2_B = -2.769034857
MQ135_CLEAN_AIR_PPM = 400.0
MQ135_DEFAULT_CLEAN_AIR_RAW = 1000.0


@dataclass(frozen=True, slots=True)
class GasCalibration:
    """Runtime MQ-135 calibration parameters."""

    r0_kohm: float
    vcc: float = MQ135_VCC
    rl_kohm: float = MQ135_RL_KOHM
    adc_max_mv: float = ESP32_ADC_MAX_MV
    adc_max_raw: float = ESP32_ADC_MAX_RAW
    divider_top_kohm: float = MQ135_DIVIDER_TOP_KOHM
    divider_bottom_kohm: float = MQ135_DIVIDER_BOTTOM_KOHM
    co2_a: float = MQ135_CO2_A
    co2_b: float = MQ135_CO2_B


def calculate_gas_ppm(raw: Any, r0_kohm: float | None = None) -> float:
    """Convert ESP32 ADC raw value into estimated CO2 ppm."""

    calibration = GasCalibration(r0_kohm=_positive(r0_kohm, DEFAULT_MQ135_R0_KOHM))
    rs = raw_to_rs_kohm(raw, calibration)
    if rs <= 0.0 or calibration.r0_kohm <= 0.0:
        return 0.0
    ratio = rs / calibration.r0_kohm
    if ratio <= 0.0:
        return 0.0
    ppm = calibration.co2_a * pow(ratio, calibration.co2_b)
    if not isfinite(ppm):
        return 0.0
    return max(0.0, min(ppm, 99999.0))


def calibrate_r0_from_clean_air_raw(raw: Any, clean_air_ppm: float = MQ135_CLEAN_AIR_PPM) -> float:
    """Infer R0 from the current raw value in clean air at a known CO2 ppm."""

    rs = raw_to_rs_kohm(raw, GasCalibration(r0_kohm=1.0))
    ppm = _positive(clean_air_ppm, MQ135_CLEAN_AIR_PPM)
    if rs <= 0.0:
        return DEFAULT_MQ135_R0_KOHM if "DEFAULT_MQ135_R0_KOHM" in globals() else 1.0
    ratio_at_ppm = pow(ppm / MQ135_CO2_A, 1.0 / MQ135_CO2_B)
    if not isfinite(ratio_at_ppm) or ratio_at_ppm <= 0.0:
        return DEFAULT_MQ135_R0_KOHM if "DEFAULT_MQ135_R0_KOHM" in globals() else 1.0
    return max(0.001, rs / ratio_at_ppm)


def raw_to_rs_kohm(raw: Any, calibration: GasCalibration | None = None) -> float:
    """Convert ESP32 ADC raw value into MQ sensor resistance in kOhm."""

    cfg = calibration or GasCalibration(r0_kohm=DEFAULT_MQ135_R0_KOHM)
    raw_value = _positive(raw, 0.0)
    if raw_value <= 0.0:
        return 0.0
    raw_value = min(raw_value, cfg.adc_max_raw)
    adc_voltage = (raw_value / cfg.adc_max_raw) * (cfg.adc_max_mv / 1000.0)
    mq_voltage = adc_voltage * (cfg.divider_top_kohm + cfg.divider_bottom_kohm) / cfg.divider_bottom_kohm
    mq_voltage = max(0.001, min(mq_voltage, cfg.vcc - 0.001))
    rs = ((cfg.vcc - mq_voltage) * cfg.rl_kohm) / mq_voltage
    if not isfinite(rs):
        return 0.0
    return max(0.0, rs)


def _positive(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not isfinite(number) or number <= 0.0:
        return default
    return number

def default_r0_kohm() -> float:
    """Return a conservative startup R0 inferred from a nominal clean-air raw value."""

    return calibrate_r0_from_clean_air_raw(MQ135_DEFAULT_CLEAN_AIR_RAW)


DEFAULT_MQ135_R0_KOHM = default_r0_kohm()