"""ERA5 原始日变量 → 气候指标。仅读取所选输出所需的输入。"""
import logging
import numpy as np

from climate_math import precipitation_mm_day, wet_days, relative_humidity, output_metadata
from raster_io import Raster, check_grid, daily_files, read_tif, write_tif

LOG = logging.getLogger(__name__)
REQUIREMENTS = {
    "hurs": ("d2m", "t2m"), "pre": ("avg_tprate",), "wdf": ("avg_tprate",),
    "rad": ("avg_sdswrf",), "wnd": ("u10", "v10"), "tmx": ("mx2t",), "tmn": ("mn2t",),
}


def run(config):
    needed = sorted({v for output in config.variables for v in REQUIREMENTS[output]})
    root = config.tif_root / config.scenario
    files = {v: daily_files(root / v) for v in needed}
    dates = set(files[needed[0]])
    if any(set(files[v]) != dates for v in needed):
        raise ValueError("ERA5 各输入变量的每日日期集合不一致，请先补齐数据")
    for name in sorted(dates):
        inputs = {v: read_tif(files[v][name]) for v in needed}
        reference = inputs[needed[0]]
        for var, raster in inputs.items():
            check_grid(reference, raster, files[var][name])
        arrays = {v: raster.data for v, raster in inputs.items()}
        for output in config.variables:
            if output == "hurs":
                data = relative_humidity(arrays["d2m"], arrays["t2m"])
            elif output in ("pre", "wdf"):
                data = precipitation_mm_day(arrays["avg_tprate"], config.precipitation_unit)
                if output == "wdf":
                    data = wet_days(data, config.wet_day_threshold_mm)
            elif output == "wnd":
                data = np.hypot(arrays["u10"], arrays["v10"])
            elif output == "rad":
                data = arrays["avg_sdswrf"]
            else:
                data = arrays[REQUIREMENTS[output][0]] - 273.15
            raster = Raster(data * config.scales[output], reference.transform, reference.projection,
                            output_metadata(config, output, reference.metadata))
            write_tif(config.daily_root / config.scenario / output / name, raster,
                      config.nodata, integer=True, overwrite=config.overwrite)
        LOG.info("ERA5 日指标完成: %s", name)
