"""参考实例和默认运行配置；修改 CONFIGS 后直接运行 Runner.py。"""
from pathlib import Path

from Config import ERA5, CMIP6, ERA5_FILES, MODELS

# ---------- 可移植配置：root_path 下按 README 的结构放置数据 ----------
PROJECT_ROOT = Path(__file__).resolve().parent / "workspace"
ERA5_EXAMPLE = ERA5(root_path=PROJECT_ROOT, var_dict=ERA5_FILES.copy())
CMIP6_EXAMPLE = CMIP6(root_path=PROJECT_ROOT, scenarios=("ssp245",),
                       models=MODELS, variables=("rad",))

# ---------- 原脚本的网络目录配置，仅供参考，默认不执行 ----------
# 公开发布前可将这些个人路径改为通用占位路径。
SHARE = Path("D:/climate_data")
ERA5_PERSONAL = ERA5(
    name="ERA5_personal", nc_folder=SHARE / "origin_history_NetCDFdata",
    tif_root=SHARE / "origin_history_Tifdata",  # 程序自动追加 history/变量
    daily_root=SHARE / "daily_data", monthly_root=SHARE / "month_data",
    result_root=SHARE / "month_result", mask_path=SHARE / "mask/2020-12.tif",
    time_field="valid_time", var_dict=ERA5_FILES.copy(), mask_backend="arcpy",
)
CMIP6_PERSONAL = CMIP6(
    name="CMIP6_personal", nc_folder=SHARE / "origin_future_NetCDFdata",
    tif_root=SHARE / "origin_future_Tifdata", daily_root=SHARE / "daily_data",
    monthly_root=SHARE / "month_data", result_root=SHARE / "month_result",
    mask_path=SHARE / "mask/2020-12.tif", scenarios=("ssp245",), models=MODELS,
    variables=("rad",), time_field="time", mask_backend="arcpy",
)

# 原 make_daily_tif_CMIP6.py / daily_to_month.py / rename.py 的当前本地配置。
# 已有 rsds_模型 日 TIFF，从 daily 阶段继续；输出目录保持原配置。
CMIP6_RAD_2023 = CMIP6(
    name="CMIP6_rad_2023", nc_folder=SHARE / "origin_future_NetCDFdata",
    tif_root=Path("E:/rad_2023"), daily_root=Path("E:/rad_2023/rsds_daily_data"),
    monthly_root=Path("E:/rad_2023/rsds_month_data"),
    result_root=Path("E:/rad_2023/rsds_result"),
    mask_path=SHARE / "mask/2020-12.tif", scenarios=("ssp245",), models=MODELS,
    variables=("rad",), stages=("daily", "monthly", "mask", "rename"),
)

# 一键运行入口读取此列表。可以同时放入 ERA5 和 CMIP6 实例。
# 默认使用通用路径；不会自动访问上面的个人网络目录或原有输出。
CONFIGS = [ERA5_EXAMPLE, CMIP6_EXAMPLE]
