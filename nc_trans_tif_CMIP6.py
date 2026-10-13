"""CMIP6 NetCDF → 情景 / 变量_模型 / 每日 TIFF。"""
from netcdf_io import convert_file


def run(config):
    jobs = []
    sources = sorted({config.source_variables[v] for v in config.variables})
    for scenario in config.scenarios:
        for var in sources:
            directory = config.nc_folder / scenario / var
            if not directory.is_dir():
                raise FileNotFoundError(directory)
            selected = []
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() != ".nc":
                    continue
                parts = path.stem.split("_")
                if len(parts) <= config.model_name_index:
                    raise ValueError(f"无法识别模型名称，请检查 model_name_index: {path}")
                model = parts[config.model_name_index]
                if model in config.models:
                    selected.append((path, var, config.tif_root / scenario / f"{var}_{model}"))
            if not selected:
                raise ValueError(f"没有符合 models 配置的 NetCDF 文件: {directory}")
            jobs.extend(selected)
    for path, var, output in jobs:
        convert_file(path, var, output, config)
