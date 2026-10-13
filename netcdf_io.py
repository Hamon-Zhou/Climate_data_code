"""ERA5 / CMIP6 公用 NetCDF 转换，保留 CF 历法。"""
from pathlib import Path
import logging

import numpy as np
from netCDF4 import Dataset, num2date
from osgeo import osr

from raster_io import Raster, write_tif

LOG = logging.getLogger(__name__)


def ordered_grid(lat, lon, normalize_longitude=True):
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    if lat.ndim != 1 or lon.ndim != 1 or min(len(lat), len(lon)) < 2:
        raise ValueError("仅支持至少 2×2 的一维经纬度规则网格；曲线网格需先重网格化")
    if not np.all(np.isfinite(lat)) or not np.all(np.isfinite(lon)):
        raise ValueError("经纬度坐标含无效值")
    if normalize_longitude:
        lon = (lon + 180) % 360 - 180
    iy, ix = np.argsort(-lat), np.argsort(lon)
    lat, lon = lat[iy], lon[ix]
    dx, dy = np.diff(lon), -np.diff(lat)
    if (np.any(dx <= 0) or np.any(dy <= 0) or
            not np.allclose(dx, dx[0], rtol=1e-5, atol=1e-6) or
            not np.allclose(dy, dy[0], rtol=1e-5, atol=1e-6)):
        raise ValueError("经纬度必须等间距且无重复；跨日期变更线的区域可设置 normalize_longitude=False")
    return iy, ix, (lon[0] - dx[0] / 2, dx[0], 0,
                    lat[0] + dy[0] / 2, 0, -dy[0])


def convert_file(path, variable_name, output_dir, config):
    path, output_dir = Path(path), Path(output_dir)
    with Dataset(str(path), "r") as nc:
        for key in (variable_name, config.latitude_name, config.longitude_name, config.time_field):
            if key not in nc.variables:
                raise KeyError(f"{path} 缺少变量/坐标: {key}")
        var = nc.variables[variable_name]
        # netCDF4 自动处理 scale_factor/add_offset、_FillValue、missing_value。
        var.set_auto_maskandscale(True)
        lat, lon = nc.variables[config.latitude_name], nc.variables[config.longitude_name]
        time = nc.variables[config.time_field]
        if len(lat.dimensions) != 1 or len(lon.dimensions) != 1 or len(time.dimensions) != 1:
            raise ValueError(f"仅支持一维时间、纬度、经度坐标: {path}")
        time_dim, lat_dim, lon_dim = time.dimensions[0], lat.dimensions[0], lon.dimensions[0]
        required = (time_dim, lat_dim, lon_dim)
        if len(set(required)) != 3 or any(d not in var.dimensions for d in required):
            raise ValueError(f"变量维度必须包含时间、纬度、经度: {path}, {var.dimensions}")
        for dim in var.dimensions:
            if dim not in required and len(nc.dimensions[dim]) != 1:
                raise ValueError(f"额外维度 {dim} 长度大于 1，请先选择成员/层次: {path}")
        if not getattr(time, "units", None):
            raise ValueError(f"时间字段没有 units: {path}")
        calendar = getattr(time, "calendar", "standard")
        dates = num2date(time[:], time.units, calendar=calendar)
        names = [dt.strftime("%Y-%m-%d") + ".tif" for dt in dates]
        if not names or len(set(names)) != len(names):
            raise ValueError(f"需要每日一个时间步，不支持同一天多个时次或空时间轴: {path}")
        iy, ix, gt = ordered_grid(lat[:], lon[:], config.normalize_longitude)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        remaining = [d for d in var.dimensions if d in (lat_dim, lon_dim)]
        for i, name in enumerate(names):
            index = tuple(i if dim == time_dim else slice(None) if dim in (lat_dim, lon_dim) else 0
                          for dim in var.dimensions)
            data = np.ma.asarray(var[index], dtype=np.float64).filled(np.nan)
            if remaining != [lat_dim, lon_dim]:
                data = data.T
            data = data[np.ix_(iy, ix)]
            data[~np.isfinite(data)] = np.nan
            metadata = {"CALENDAR": calendar, "SOURCE_VARIABLE": variable_name,
                        "UNITS": getattr(var, "units", ""), "DATE": name[:-4]}
            write_tif(output_dir / name, Raster(data, gt, srs.ExportToWkt(), metadata),
                      config.nodata, overwrite=config.overwrite)
        LOG.info("转换 %s：%s 个日文件 → %s", path.name, len(names), output_dir)
