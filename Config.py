"""配置类型；此模块只定义配置，不读取数据、不创建目录。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import math
import os
import re

ROOT = Path(__file__).resolve().parent
STAGES = ("nc", "daily", "monthly", "mask", "rename")
VARIABLES = ("hurs", "pre", "wdf", "rad", "wnd", "tmx", "tmn")
ERA5_FILES = {
    "2m_dewpoint_temperature_0_daily-mean.nc": "d2m",
    "2m_temperature_0_daily-mean.nc": "t2m",
    "10m_u_component_of_wind_stream-oper_daily-mean.nc": "u10",
    "10m_v_component_of_wind_0_daily-mean.nc": "v10",
    "maximum_2m_temperature_since_previous_post_processing_0_daily-mean.nc": "mx2t",
    "minimum_2m_temperature_since_previous_post_processing_0_daily-mean.nc": "mn2t",
    "mean_surface_downward_short_wave_radiation_flux_0_daily-mean.nc": "avg_sdswrf",
    "mean_total_precipitation_rate.nc": "avg_tprate",
}
CMIP6_VARIABLES = {
    "hurs": "hurs", "pre": "pr", "wdf": "pr", "rad": "rsds",
    "wnd": "sfcWind", "tmx": "tasmax", "tmn": "tasmin",
}
MODELS = ("BCC-CSM2-MR", "CanESM5", "CNRM-CM6-1", "HadGEM3-GC31-LL",
          "IPSL-CM6A-LR", "MIROC6", "MRI-ESM2-0")


@dataclass
class CommonConfig:
    name: str = "climate"
    enabled: bool = True
    root_path: Path = ROOT / "workspace"
    nc_folder: Optional[Path] = None
    tif_root: Optional[Path] = None
    daily_root: Optional[Path] = None
    monthly_root: Optional[Path] = None
    result_root: Optional[Path] = None
    mask_path: Optional[Path] = None
    stages: tuple[str, ...] = STAGES
    variables: tuple[str, ...] = VARIABLES
    scales: dict[str, float] = field(default_factory=lambda: {
        "hurs": 100, "pre": 10, "wdf": 100, "rad": 100,
        "wnd": 100, "tmx": 100, "tmn": 100,
    })
    results_unit_dict: dict[str, str] = field(default_factory=lambda: {
        "hurs": "%", "pre": "mm/day", "wdf": "wet day indicator",
        "rad": "W m-2", "wnd": "m s-1", "tmx": "degC", "tmn": "degC",
    })
    monthly_methods: dict[str, str] = field(default_factory=lambda: {
        "hurs": "mean", "pre": "sum", "wdf": "sum", "rad": "sum",
        "wnd": "mean", "tmx": "mean", "tmn": "mean",
    })
    # mean_total_precipitation_rate / pr 默认 kg m-2 s-1，即 mm/s。
    precipitation_unit: str = "kg m-2 s-1"
    wet_day_threshold_mm: float = 1.0
    nodata: int = -9999
    overwrite: bool = False
    normalize_longitude: bool = True
    mask_backend: str = "gdal"  # 也可以使用原有的 arcpy 后端。
    resampling: str = "bilinear"
    mask_zero_is_nodata: bool = False
    remove_month_leading_zero: bool = True

    def __post_init__(self):
        root = Path(self.root_path).expanduser()
        self.root_path = root if root.is_absolute() else ROOT / root
        defaults = {"nc_folder": self.root_path / "netcdf" / self.name,
                    "tif_root": self.root_path / "raw_tif" / self.name,
                    "daily_root": self.root_path / "daily",
                    "monthly_root": self.root_path / "monthly",
                    "result_root": self.root_path / "result",
                    "mask_path": self.root_path / "mask.tif"}
        for key in defaults:
            value = getattr(self, key)
            path = Path(value).expanduser() if value is not None else defaults[key]
            setattr(self, key, path if path.is_absolute() else ROOT / path)

    def validate(self):
        if not self.stages or len(set(self.stages)) != len(self.stages):
            raise ValueError("stages 不得为空或重复")
        if any(s not in STAGES for s in self.stages):
            raise ValueError(f"stages 只能从 {STAGES} 中选择")
        if not self.variables or len(set(self.variables)) != len(self.variables):
            raise ValueError("variables 不得为空或重复")
        if any(v not in VARIABLES for v in self.variables):
            raise ValueError(f"variables 只能从 {VARIABLES} 中选择")
        for var in self.variables:
            if not math.isfinite(self.scales.get(var, 0)) or self.scales.get(var, 0) <= 0:
                raise ValueError(f"{var} 的 scales 必须为正数")
            if self.monthly_methods.get(var) not in ("sum", "mean"):
                raise ValueError(f"{var} 的 monthly_methods 必须为 sum 或 mean")
            if not self.results_unit_dict.get(var):
                raise ValueError(f"results_unit_dict 缺少 {var} 的单位")
        if self.precipitation_unit not in ("kg m-2 s-1", "mm/s", "m/s", "mm/day", "m/day"):
            raise ValueError("不支持的 precipitation_unit")
        if not math.isfinite(self.wet_day_threshold_mm) or self.wet_day_threshold_mm < 0:
            raise ValueError("wet_day_threshold_mm 必须为非负数")
        if self.nodata != int(self.nodata) or not -(2**31) <= self.nodata < 2**31:
            raise ValueError("nodata 必须是 Int32 范围内的整数")
        if self.mask_backend not in ("gdal", "arcpy"):
            raise ValueError("mask_backend 必须为 gdal 或 arcpy")
        if self.resampling not in ("near", "bilinear", "cubic", "average"):
            raise ValueError("不支持的 resampling")
        if "mask" in self.stages and self.mask_path is None:
            raise ValueError("执行 mask 步骤需要 mask_path")
        # 只做词法规范化；resolve() 可能访问 UNC 共享，dry-run 也不应触碰网络。
        paths = [os.path.normcase(os.path.abspath(p)) for p in (
            self.nc_folder, self.tif_root, self.daily_root, self.monthly_root, self.result_root)]
        for i, path in enumerate(paths):
            for other in paths[i + 1:]:
                if path == other:
                    raise ValueError("输入和各阶段输出目录不能相同")
        for label in self.scenarios:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", label) or label in (".", ".."):
                raise ValueError(f"不安全的情景名称: {label}")


@dataclass
class ERA5(CommonConfig):
    name: str = "ERA5"
    scenario: str = "history"
    time_field: str = "valid_time"
    latitude_name: str = "latitude"
    longitude_name: str = "longitude"
    var_dict: dict[str, str] = field(default_factory=lambda: ERA5_FILES.copy())

    @property
    def scenarios(self):
        return (self.scenario,)


@dataclass
class CMIP6(CommonConfig):
    name: str = "CMIP6"
    scenarios: tuple[str, ...] = ("ssp126", "ssp245", "ssp370", "ssp585")
    models: tuple[str, ...] = MODELS
    source_variables: dict[str, str] = field(default_factory=lambda: CMIP6_VARIABLES.copy())
    time_field: str = "time"
    latitude_name: str = "lat"
    longitude_name: str = "lon"
    model_name_index: int = 2  # CMIP6 标准文件名 var_day_MODEL_...nc
    min_models: int = 1
    model_grid_policy: str = "strict"  # align: 重采样到第一个配置模型的网格

    def validate(self):
        super().validate()
        if not self.scenarios or len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("scenarios 不得为空或重复")
        if not self.models or len(set(self.models)) != len(self.models):
            raise ValueError("models 不得为空或重复")
        if not 1 <= self.min_models <= len(self.models):
            raise ValueError("min_models 必须介于 1 和模型总数之间")
        if self.model_grid_policy not in ("strict", "align"):
            raise ValueError("model_grid_policy 必须为 strict 或 align")
        if self.model_name_index < 0:
            raise ValueError("model_name_index 不得为负数")
        for value in (*self.models, *self.source_variables.values()):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", ".."):
                raise ValueError(f"不安全的模型或变量名称: {value}")
        if any(v not in self.source_variables for v in self.variables):
            raise ValueError("source_variables 缺少所选输出变量")
