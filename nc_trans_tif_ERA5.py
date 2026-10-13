"""ERA5 NetCDF → 按原始变量分目录的每日 TIFF。"""
from netcdf_io import convert_file
from make_daily_tif_ERA5 import REQUIREMENTS


def run(config):
    needed = {source for output in config.variables for source in REQUIREMENTS[output]}
    selected = [(filename, var) for filename, var in config.var_dict.items() if var in needed]
    if needed - {var for _, var in selected}:
        raise ValueError(f"var_dict 缺少原始变量: {needed - {var for _, var in selected}}")
    # 全部文件存在后再开始转换。
    for filename, _ in selected:
        if not (config.nc_folder / filename).is_file():
            raise FileNotFoundError(config.nc_folder / filename)
    for filename, var in selected:
        convert_file(config.nc_folder / filename, var,
                     config.tif_root / config.scenario / var, config)
