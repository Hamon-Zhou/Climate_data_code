"""统一 ERA5/CMIP6 月聚合；默认沿用原脚本的 sum / mean 规则。"""
from collections import defaultdict
import logging

from raster_io import aggregate, daily_files, write_tif

LOG = logging.getLogger(__name__)


def run(config):
    for scenario in config.scenarios:
        for variable in config.variables:
            files = daily_files(config.daily_root / scenario / variable)
            groups = defaultdict(list)
            for name, path in files.items():
                groups[name[:7]].append(path)
            method = config.monthly_methods[variable]
            for month, paths in sorted(groups.items()):
                raster = aggregate(paths, method)
                raster.metadata.update({"AGGREGATION": method, "MONTH": month,
                                        "DAYS_PRESENT": str(len(paths)), "VARIABLE": variable,
                                        "STORED_MULTIPLIER": str(config.scales[variable])})
                raster.metadata.pop("DATE", None)
                raster.metadata.pop("MODELS", None)  # 每日参与模型可能不同。
                if variable == "pre" and method == "sum":
                    raster.metadata["UNITS"] = "mm/month"
                elif variable == "wdf" and method == "sum":
                    raster.metadata["UNITS"] = "wet days/month"
                elif variable == "rad" and method == "sum":
                    raster.metadata["UNITS"] = "sum of daily mean W m-2 (not energy)"
                write_tif(config.monthly_root / scenario / variable / f"{month}.tif", raster,
                          config.nodata, integer=True, overwrite=config.overwrite)
                LOG.info("月聚合 %s/%s/%s: %s, %d 日", scenario, variable, month, method, len(paths))
