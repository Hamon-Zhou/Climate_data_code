"""CMIP6 多模型等权均值 → 气候指标；先平均降水，再判断湿日。"""
import logging

from climate_math import precipitation_mm_day, wet_days, output_metadata
from raster_io import Raster, aggregate, daily_files, read_tif, write_tif

LOG = logging.getLogger(__name__)


def run(config):
    sources = sorted({config.source_variables[v] for v in config.variables})
    for scenario in config.scenarios:
        for source in sources:
            model_files = {}
            for model in config.models:
                directory = config.tif_root / scenario / f"{source}_{model}"
                if directory.is_dir():
                    model_files[model] = daily_files(directory)
                else:
                    LOG.warning("模型目录缺失: %s", directory)
            if not model_files:
                raise ValueError(f"没有可用模型: {scenario}/{source}")
            dates = sorted(set().union(*(set(files) for files in model_files.values())))
            first_files = next(iter(model_files.values()))
            # 固定参考网格，防止某天首个模型缺失时输出网格改变。
            reference_grid = read_tif(first_files[sorted(first_files)[0]])
            for name in dates:
                available = [(model, files[name]) for model, files in model_files.items() if name in files]
                if len(available) < config.min_models:
                    raise ValueError(f"{scenario}/{source}/{name}: 可用模型数 {len(available)} < min_models")
                if len(available) < len(config.models):
                    LOG.warning("%s/%s/%s 使用 %d/%d 个模型", scenario, source, name,
                                len(available), len(config.models))
                average = aggregate([path for _, path in available], "mean",
                                    config.model_grid_policy, config.resampling, reference_grid)
                for output in config.variables:
                    if config.source_variables[output] != source:
                        continue
                    data = average.data
                    if output in ("pre", "wdf"):
                        data = precipitation_mm_day(data, config.precipitation_unit)
                        if output == "wdf":
                            data = wet_days(data, config.wet_day_threshold_mm)
                    elif output in ("tmx", "tmn"):
                        data = data - 273.15
                    metadata = output_metadata(config, output, average.metadata)
                    metadata["MODELS"] = ",".join(model for model, _ in available)
                    metadata["MODEL_GRID_POLICY"] = config.model_grid_policy
                    raster = Raster(data * config.scales[output], average.transform,
                                    average.projection, metadata)
                    write_tif(config.daily_root / scenario / output / name, raster,
                              config.nodata, integer=True, overwrite=config.overwrite)
            LOG.info("%s/%s 多模型日指标完成", scenario, source)
