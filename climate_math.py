"""纯数组计算；输入、输出均为物理量，缺失值用 NaN 表示。"""
import numpy as np


def precipitation_mm_day(data, unit):
    factors = {"kg m-2 s-1": 86400, "mm/s": 86400,
               "m/s": 86400000, "mm/day": 1, "m/day": 1000}
    return np.asarray(data, dtype=np.float64) * factors[unit]


def wet_days(precipitation, threshold):
    return np.where(np.isfinite(precipitation), (precipitation >= threshold).astype(float), np.nan)


def relative_humidity(dewpoint, temperature):
    dewpoint, temperature = dewpoint - 273.15, temperature - 273.15
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result = 100 * np.exp(17.67 * dewpoint / (dewpoint + 243.5)
                              - 17.67 * temperature / (temperature + 243.5))
    return np.where(np.isfinite(result), result, np.nan)


def output_metadata(config, variable, original=None):
    result = dict(original or {})
    result.update({"VARIABLE": variable, "UNITS": config.results_unit_dict[variable],
                   "STORED_MULTIPLIER": str(config.scales[variable]),
                   "VALUE_ENCODING": "physical_value = stored_value / STORED_MULTIPLIER"})
    return result
