"""统一 NoData、网格检查、流式聚合和 GeoTIFF 写入。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import logging
import re
import uuid

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
LOG = logging.getLogger(__name__)
CREATION_OPTIONS = ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"]


@dataclass
class Raster:
    data: np.ndarray
    transform: tuple
    projection: str
    metadata: dict = field(default_factory=dict)


def read_tif(path):
    ds = gdal.Open(str(path))
    if ds is None:
        raise FileNotFoundError(f"无法打开 TIFF: {path}")
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray().astype(np.float64)
    nd = band.GetNoDataValue()
    valid = (band.GetMaskBand().ReadAsArray() != 0) & np.isfinite(data)
    if nd is not None:
        valid &= data != nd
    data[~valid] = np.nan
    result = Raster(data, ds.GetGeoTransform(), ds.GetProjection(), ds.GetMetadata())
    ds = None
    return result


def same_grid(a, b):
    if a.data.shape != b.data.shape or not np.allclose(a.transform, b.transform, rtol=0, atol=1e-9):
        return False
    if not a.projection or not b.projection:
        return a.projection == b.projection
    sa, sb = osr.SpatialReference(), osr.SpatialReference()
    sa.ImportFromWkt(a.projection)
    sb.ImportFromWkt(b.projection)
    return bool(sa.IsSame(sb))


def check_grid(a, b, path=""):
    if not same_grid(a, b):
        raise ValueError(f"栅格网格不一致（尺寸、坐标或投影）: {path}")
    ca, cb = a.metadata.get("CALENDAR"), b.metadata.get("CALENDAR")
    if ca and cb and ca != cb:
        raise ValueError(f"历法不一致: {ca} / {cb}，不能直接按同名日期聚合: {path}")


def write_tif(path, raster, nodata=-9999, integer=False, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"输出已存在: {path}；如需覆盖，设置 overwrite=True")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(raster.data)
    valid = np.isfinite(data)
    values = np.rint(data[valid]) if integer else data[valid]
    if integer and (np.any(values < -(2**31)) or np.any(values >= 2**31)):
        raise OverflowError(f"Int32 超出范围: {path}；请减小 scales")
    if np.any(values == nodata):
        raise ValueError(f"有效数据与 nodata={nodata} 冲突: {path}")
    output = np.full(data.shape, nodata, dtype=np.int32 if integer else np.float32)
    output[valid] = values
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp.tif")
    ds = None
    try:
        ds = gdal.GetDriverByName("GTiff").Create(
            str(tmp), data.shape[1], data.shape[0], 1,
            gdal.GDT_Int32 if integer else gdal.GDT_Float32,
            options=CREATION_OPTIONS,
        )
        ds.SetGeoTransform(raster.transform)
        ds.SetProjection(raster.projection)
        ds.SetMetadata({str(k): str(v) for k, v in raster.metadata.items()})
        ds.GetRasterBand(1).SetNoDataValue(float(nodata))
        ds.GetRasterBand(1).WriteArray(output)
        ds.FlushCache()
        ds = None
        tmp.replace(path)
    finally:
        ds = None
        if tmp.exists():
            tmp.unlink()


def read_on_grid(path, reference, resampling="bilinear"):
    """重投影/重采样到参考栅格的精确网格。"""
    gt = reference.transform
    if gt[2] or gt[4] or gt[1] <= 0 or gt[5] >= 0:
        raise ValueError("参考网格必须为无旋转的 north-up 网格")
    if not reference.projection:
        raise ValueError("参考栅格缺少投影")
    rows, cols = reference.data.shape
    ds = gdal.Warp(
        "", str(path), format="MEM", dstSRS=reference.projection,
        outputBounds=(gt[0], gt[3] + rows * gt[5], gt[0] + cols * gt[1], gt[3]),
        width=cols, height=rows, resampleAlg=resampling,
        outputType=gdal.GDT_Float64, dstNodata=float("nan"),
    )
    if ds is None:
        raise RuntimeError(f"重采样失败: {path}")
    data = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    result = Raster(data, ds.GetGeoTransform(), ds.GetProjection(), ds.GetMetadata())
    ds = None
    check_grid(reference, result, path)
    return result


def aggregate(paths, method="mean", grid_policy="strict", resampling="bilinear", reference_grid=None):
    """逐文件累加，避免把整月或全部模型堆叠到内存。"""
    reference = reference_grid
    seen = False
    if reference is not None:
        total = np.zeros(reference.data.shape, dtype=np.float64)
        count = np.zeros(reference.data.shape, dtype=np.int32)
    for path in paths:
        seen = True
        raster = read_tif(path)
        if reference is None:
            reference = raster
            total = np.zeros(raster.data.shape, dtype=np.float64)
            count = np.zeros(raster.data.shape, dtype=np.int32)
        elif grid_policy == "align" and not same_grid(reference, raster):
            raster = read_on_grid(path, reference, resampling)
        check_grid(reference, raster, path)
        valid = np.isfinite(raster.data)
        total += np.where(valid, raster.data, 0)
        count += valid
    if not seen:
        raise ValueError("没有可用于聚合的栅格")
    if method not in ("sum", "mean"):
        raise ValueError(f"未知聚合方法: {method}")
    result = np.full(total.shape, np.nan)
    valid = count > 0
    result[valid] = total[valid] if method == "sum" else total[valid] / count[valid]
    return Raster(result, reference.transform, reference.projection, reference.metadata.copy())


def daily_files(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"每日数据目录不存在: {directory}")
    files = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() != ".tif":
            continue
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", path.stem)
        # 不使用 datetime，允许 CMIP6 360_day 的 02-30 等日期。
        if not match or not 1 <= int(match[2]) <= 12 or not 1 <= int(match[3]) <= 31:
            raise ValueError(f"每日文件名必须是 YYYY-MM-DD.tif: {path}")
        if path.name in files:
            raise ValueError(f"重复日期文件: {path}")
        files[path.name] = path
    if not files:
        raise ValueError(f"没有每日 TIFF: {directory}")
    return files
