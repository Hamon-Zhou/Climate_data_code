"""小型真实 NetCDF/GeoTIFF 回归测试；不访问个人目录。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from netCDF4 import Dataset
from osgeo import gdal, osr

from Config import ERA5, CMIP6
from Runner import main, run
from climate_math import precipitation_mm_day, wet_days
from netcdf_io import convert_file, ordered_grid
from raster_io import Raster, aggregate, read_tif, write_tif


def projection():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    return srs.ExportToWkt()


def create_nc(path, variable, data, era=False, packed=False, calendar="standard",
              times=(0, 1), lat=(0, 1), lon=(0, 1)):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(str(path), "w") as ds:
        time_name, lat_name, lon_name = ("valid_time", "latitude", "longitude") if era else ("time", "lat", "lon")
        for name, size in ((time_name, len(times)), (lat_name, len(lat)), (lon_name, len(lon))):
            ds.createDimension(name, size)
        t = ds.createVariable(time_name, "f8", (time_name,))
        t.units = "days since 2001-01-01"
        t.calendar = calendar
        t[:] = times
        ds.createVariable(lat_name, "f8", (lat_name,))[:] = lat
        ds.createVariable(lon_name, "f8", (lon_name,))[:] = lon
        var = ds.createVariable(variable, "i2" if packed else "f4",
                                (time_name, lat_name, lon_name), fill_value=-32768 if packed else -9999)
        if packed:
            var.scale_factor = 0.5
            var.add_offset = 250.0
        safe = np.ma.masked_invalid(data)
        # 避免 netCDF4 将被掩膜的 NaN 临时转换成打包整数而产生告警。
        safe.data[~np.isfinite(safe.data)] = 250 if packed else 0
        var[:] = safe


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="climate_pipeline_test_")
        self.root = Path(self.tmp.name)
        self.gt = (-0.5, 1, 0, 1.5, 0, -1)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, data, transform=None):
        write_tif(path, Raster(np.array(data, dtype=float), transform or self.gt, projection()))

    def make_mask(self):
        path = self.root / "mask.tif"
        self.write(path, [[1, np.nan], [0, 1]])
        return path

    def test_era5_complete_pipeline(self):
        config = ERA5(root_path=self.root, variables=("hurs", "pre", "wdf", "rad", "wnd", "tmx", "tmn"))
        values = {"d2m": 283.15, "t2m": 283.15, "avg_tprate": 2 / 86400,
                  "avg_sdswrf": 10, "u10": 3, "v10": 4, "mx2t": 293.15, "mn2t": 278.15}
        for filename, var in config.var_dict.items():
            data = np.full((2, 2, 2), values[var], dtype=float)
            data[:, 0, 0] = np.nan  # south-west 像元在所有输入中无效。
            create_nc(config.nc_folder / filename, var, data, era=True)
        self.make_mask()
        run(config)
        expected = {"hurs": 10000, "pre": 40, "wdf": 200, "rad": 2000,
                    "wnd": 500, "tmx": 2000, "tmn": 500}
        for var, value in expected.items():
            path = config.result_root / "history" / var / "2001-1.tif"
            raster = read_tif(path)
            self.assertEqual(raster.data[0, 0], value)
            self.assertEqual(raster.data[1, 1], value)
            self.assertTrue(np.isnan(raster.data[0, 1]))  # mask NoData
            self.assertTrue(np.isnan(raster.data[1, 0]))  # source NoData
            self.assertEqual(raster.transform, self.gt)
            ds = gdal.Open(str(path))
            self.assertEqual(ds.GetRasterBand(1).DataType, gdal.GDT_Int32)
            ds = None

    def test_cmip6_complete_pipeline(self):
        config = CMIP6(root_path=self.root, scenarios=("ssp245",), models=("A", "B"), min_models=2)
        values = {"hurs": 60, "pr": 2 / 86400, "rsds": 10, "sfcWind": 5,
                  "tasmax": 293.15, "tasmin": 278.15}
        for model in config.models:
            for var, value in values.items():
                adjusted = value + (-2 if model == "A" else 2) if var in ("tasmax", "tasmin") else value * (0.8 if model == "A" else 1.2)
                data = np.full((2, 2, 2), adjusted, dtype=float)
                if model == "A":
                    data[:, 0, 0] = np.nan  # B 的有效值仍能参与平均。
                create_nc(config.nc_folder / "ssp245" / var / f"{var}_day_{model}_sample.nc", var, data)
        self.make_mask()
        run(config)
        expected = {"hurs": 6000, "pre": 40, "wdf": 200, "rad": 2000,
                    "wnd": 500, "tmx": 2000, "tmn": 500}
        single_model = {"hurs": 7200, "pre": 48, "wdf": 200, "rad": 2400,
                        "wnd": 600, "tmx": 2200, "tmn": 700}
        for var, value in expected.items():
            raster = read_tif(config.result_root / "ssp245" / var / "2001-1.tif")
            self.assertEqual(raster.data[0, 0], value)
            self.assertEqual(raster.data[1, 0], single_model[var])  # mask=0 默认有效，只取 B 的值。
            self.assertTrue(np.isnan(raster.data[0, 1]))

    def test_packed_scale_applied_once_and_north_up(self):
        config = ERA5(root_path=self.root, variables=("tmx",), stages=("nc",))
        path = self.root / "packed.nc"
        data = np.array([[[280, np.nan], [290, 291]], [[282, 283], [292, 293]]])
        create_nc(path, "mx2t", data, era=True, packed=True)
        convert_file(path, "mx2t", self.root / "converted", config)
        raster = read_tif(self.root / "converted/2001-01-01.tif")
        np.testing.assert_allclose(raster.data, [[290, 291], [280, np.nan]], equal_nan=True)

    def test_descending_latitude_does_not_flip(self):
        config = ERA5(root_path=self.root, variables=("tmx",), stages=("nc",))
        path = self.root / "descending.nc"
        data = np.arange(8, dtype=float).reshape(2, 2, 2)
        create_nc(path, "mx2t", data, era=True, lat=(1, 0))
        convert_file(path, "mx2t", self.root / "converted", config)
        np.testing.assert_equal(read_tif(self.root / "converted/2001-01-01.tif").data, data[0])

    def test_longitude_reorders_columns(self):
        iy, ix, gt = ordered_grid([0, 1], [0, 90, 180, 270])
        np.testing.assert_equal(iy, [1, 0])
        np.testing.assert_equal(ix, [2, 3, 0, 1])
        self.assertEqual(gt[0], -225)

    def test_streaming_aggregation_ignores_nodata(self):
        a, b = self.root / "a.tif", self.root / "b.tif"
        self.write(a, [[np.nan, 2], [4, np.nan]])
        self.write(b, [[np.nan, 6], [np.nan, 10]])
        np.testing.assert_allclose(aggregate([a, b], "mean").data,
                                   [[np.nan, 4], [4, 10]], equal_nan=True)
        np.testing.assert_allclose(aggregate([a, b], "sum").data,
                                   [[np.nan, 8], [4, 10]], equal_nan=True)

    def test_grid_mismatch_is_not_silently_averaged(self):
        a, b = self.root / "a.tif", self.root / "b.tif"
        self.write(a, [[1, 1], [1, 1]])
        self.write(b, [[2, 2], [2, 2]], (-0.25, 1, 0, 1.5, 0, -1))
        with self.assertRaisesRegex(ValueError, "网格不一致"):
            aggregate([a, b])
        aligned = aggregate([a, b], grid_policy="align", resampling="near")
        self.assertEqual(aligned.transform, self.gt)

    def test_360_day_calendar_monthly_dates(self):
        config = CMIP6(root_path=self.root, scenarios=("ssp245",), models=("A",),
                       variables=("rad",), stages=("nc", "daily", "monthly"))
        path = config.nc_folder / "ssp245/rsds/rsds_day_A_sample.nc"
        create_nc(path, "rsds", np.ones((2, 2, 2)), calendar="360_day", times=(58, 59))
        run(config)
        self.assertTrue((config.daily_root / "ssp245/rad/2001-02-30.tif").is_file())
        raster = read_tif(config.monthly_root / "ssp245/rad/2001-02.tif")
        self.assertEqual(raster.data[0, 0], 200)
        self.assertEqual(raster.metadata["CALENDAR"], "360_day")

    def test_duplicate_intraday_times_rejected(self):
        config = CMIP6(root_path=self.root, variables=("rad",), stages=("nc",))
        path = self.root / "hourly.nc"
        create_nc(path, "rsds", np.ones((2, 2, 2)), times=(0, 0.5))
        with self.assertRaisesRegex(ValueError, "每日一个时间步"):
            convert_file(path, "rsds", self.root / "converted", config)

    def test_precipitation_units_and_missing_wet_days(self):
        for unit, value in (("kg m-2 s-1", 1 / 86400), ("m/s", 1 / 86400000),
                            ("m/day", 0.001), ("mm/day", 1)):
            np.testing.assert_allclose(precipitation_mm_day(np.array([value]), unit), [1])
        np.testing.assert_allclose(wet_days(np.array([0.5, 1, np.nan]), 1), [0, 1, np.nan], equal_nan=True)

    def test_overwrite_protection_and_int32_overflow(self):
        path = self.root / "out.tif"
        self.write(path, [[1, 2], [3, 4]])
        with self.assertRaises(FileExistsError):
            self.write(path, [[5, 6], [7, 8]])
        with self.assertRaises(OverflowError):
            write_tif(self.root / "big.tif", Raster(np.full((2, 2), 2**40), self.gt, projection()), integer=True)

    def test_min_models_enforced(self):
        config = CMIP6(root_path=self.root, scenarios=("ssp245",), models=("A", "B"),
                       min_models=2, variables=("rad",), stages=("daily",))
        self.write(config.tif_root / "ssp245/rsds_A/2001-01-01.tif", [[1, 1], [1, 1]])
        with self.assertRaisesRegex(ValueError, "min_models"):
            run(config)

    def test_mask_zero_can_be_excluded(self):
        config = ERA5(root_path=self.root, variables=("rad",), stages=("mask",), mask_zero_is_nodata=True)
        self.make_mask()
        self.write(config.monthly_root / "history/rad/2001-01.tif", [[1, 1], [1, 1]])
        run(config)
        raster = read_tif(config.result_root / "history/rad/2001-01.tif")
        self.assertTrue(np.isnan(raster.data[1, 0]))

    def test_runner_loads_config_and_dry_run_does_not_create_directories(self):
        path = self.root / "settings.py"
        path.write_text("from Config import ERA5\nCONFIGS = [ERA5(root_path=" + repr(str(self.root / "unused")) + ")]\n", encoding="utf-8")
        self.assertEqual(main(["--config", str(path), "--dry-run"]), 0)
        self.assertFalse((self.root / "unused").exists())

    def test_personal_samples_validate_without_resolving_network_paths(self):
        import Samples
        with patch.object(Path, "resolve", side_effect=AssertionError("不应访问文件系统解析路径")):
            for config in (Samples.ERA5_PERSONAL, Samples.CMIP6_PERSONAL, Samples.CMIP6_RAD_2023):
                config.validate()

    def test_netcdf_dimension_order_is_respected(self):
        config = CMIP6(root_path=self.root, variables=("rad",), stages=("nc",))
        path = self.root / "permuted.nc"
        data = np.arange(8, dtype=float).reshape(2, 2, 2)
        create_nc(path, "other", data)
        with Dataset(str(path), "a") as ds:
            ds.createVariable("rsds", "f4", ("lon", "time", "lat"))[:] = data.transpose(2, 0, 1)
        convert_file(path, "rsds", self.root / "converted", config)
        np.testing.assert_equal(read_tif(self.root / "converted/2001-01-01.tif").data, data[0, ::-1, :])


if __name__ == "__main__":
    unittest.main()
