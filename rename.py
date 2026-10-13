"""可选的月份去前导零步骤；只修改重构流程的输出。"""
import logging
import re

LOG = logging.getLogger(__name__)


def run(config):
    if not config.remove_month_leading_zero:
        return
    root = config.result_root if "mask" in config.stages else config.monthly_root
    jobs = []
    for scenario in config.scenarios:
        for variable in config.variables:
            directory = root / scenario / variable
            if not directory.is_dir():
                raise FileNotFoundError(directory)
            for path in sorted(directory.iterdir()):
                match = re.fullmatch(r"(\d{4})-0([1-9])\.tif", path.name, re.IGNORECASE)
                if match:
                    target = path.with_name(f"{match[1]}-{match[2]}.tif")
                    if target.exists() and not config.overwrite:
                        raise FileExistsError(f"重命名目标已存在: {target}")
                    jobs.append((path, target))
    for path, target in jobs:
        path.replace(target)
        LOG.info("重命名: %s → %s", path.name, target.name)
