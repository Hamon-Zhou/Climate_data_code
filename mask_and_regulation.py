"""掩膜、投影和网格对齐；支持 GDAL 和原有 ArcPy 后端。"""
import logging
import re
import numpy as np

from raster_io import Raster, read_tif, read_on_grid, write_tif

LOG = logging.getLogger(__name__)


def monthly_jobs(config):
    jobs = []
    for scenario in config.scenarios:
        for variable in config.variables:
            directory = config.monthly_root / scenario / variable
            if not directory.is_dir():
                raise FileNotFoundError(directory)
            paths = [p for p in sorted(directory.iterdir()) if p.suffix.lower() == ".tif"]
            if not paths:
                raise ValueError(f"没有月数据: {directory}")
            for path in paths:
                if not re.fullmatch(r"\d{4}-(0?[1-9]|1[0-2])", path.stem):
                    raise ValueError(f"月文件名应为 YYYY-MM.tif 或 YYYY-M.tif: {path}")
                output = config.result_root / scenario / variable / path.name
                if output.exists() and not config.overwrite:
                    raise FileExistsError(output)
                jobs.append((path, output))
    return jobs


def run(config):
    if not config.mask_path.is_file():
        raise FileNotFoundError(f"掩膜不存在: {config.mask_path}")
    jobs = monthly_jobs(config)
    if config.mask_backend == "arcpy":
        return run_arcpy(config, jobs)
    mask = read_tif(config.mask_path)
    valid = np.isfinite(mask.data)
    if config.mask_zero_is_nodata:
        valid &= mask.data != 0
    if not valid.any():
        raise ValueError("掩膜没有有效像元")
    for path, output in jobs:
        aligned = read_on_grid(path, mask, config.resampling)
        aligned.data[~valid] = np.nan
        aligned.metadata["MASK"] = config.mask_path.name
        write_tif(output, aligned, config.nodata, integer=True, overwrite=config.overwrite)
        LOG.info("掩膜完成: %s", output)


def run_arcpy(config, jobs):
    import arcpy
    from arcpy.sa import ExtractByMask, Raster as ArcRaster, SetNull

    if arcpy.CheckExtension("Spatial") != "Available":
        raise RuntimeError("ArcPy Spatial Analyst 许可不可用")
    arcpy.CheckOutExtension("Spatial")
    try:
        mask = ArcRaster(str(config.mask_path))
        methods = {"near": "NEAREST", "bilinear": "BILINEAR", "cubic": "CUBIC"}
        if config.resampling not in methods:
            raise ValueError("ArcPy 后端仅支持 near、bilinear、cubic")
        with arcpy.EnvManager(
            overwriteOutput=config.overwrite, snapRaster=mask, extent=mask.extent,
            cellSize=mask, outputCoordinateSystem=mask.spatialReference,
            resamplingMethod=methods[config.resampling],
        ):
            extraction_mask = SetNull(mask == 0, mask) if config.mask_zero_is_nodata else mask
            for path, output in jobs:
                output.parent.mkdir(parents=True, exist_ok=True)
                ExtractByMask(str(path), extraction_mask).save(str(output))
                LOG.info("ArcPy 掩膜完成: %s", output)
    finally:
        arcpy.CheckInExtension("Spatial")
