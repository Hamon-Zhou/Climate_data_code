"""复制为 LocalConfig.py 并修改路径; Runner.py 会优先读取 LocalConfig.py"""
from pathlib import Path
from Config import ERA5, CMIP6

ROOT_PATH = Path("./workspace")
CONFIGS = [
    ERA5(root_path=ROOT_PATH, time_field="valid_time"),
    CMIP6(root_path=ROOT_PATH, scenarios=("ssp245",), variables=("rad",),
          model_grid_policy="strict"),
]
