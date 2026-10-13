"""唯一运行入口：修改 Samples.CONFIGS，随后在 IDE 中点击运行即可。"""
from __future__ import annotations

import argparse
from dataclasses import replace
import importlib
import importlib.util
import logging
from pathlib import Path
import sys

from Config import ERA5, CMIP6, STAGES

LOG = logging.getLogger(__name__)


def run(config):
    config.validate()
    if not config.enabled:
        LOG.info("跳过禁用配置: %s", config.name)
        return
    modules = {
        "nc": "nc_trans_tif_ERA5" if isinstance(config, ERA5) else "nc_trans_tif_CMIP6",
        "daily": "make_daily_tif_ERA5" if isinstance(config, ERA5) else "make_daily_tif_CMIP6",
        "monthly": "daily_to_month", "mask": "mask_and_regulation", "rename": "rename",
    }
    if not isinstance(config, (ERA5, CMIP6)):
        raise TypeError("CONFIGS 只接受 ERA5 或 CMIP6 配置实例")
    LOG.info("运行 %s；步骤: %s", config.name, ", ".join(s for s in STAGES if s in config.stages))
    for stage in STAGES:
        if stage in config.stages:
            LOG.info("[%s] 开始 %s", config.name, stage)
            importlib.import_module(modules[stage]).run(config)
    final_root = config.result_root if "mask" in config.stages else (
        config.monthly_root if "monthly" in config.stages or "rename" in config.stages else
        config.daily_root if "daily" in config.stages else config.tif_root)
    LOG.info("%s 完成，输出目录: %s", config.name, final_root)


def load_configs(path=None):
    if path is None:
        # 优先读取本机配置，避免把个人路径提交到 GitHub。
        local = Path(__file__).resolve().parent / "LocalConfig.py"
        path = local if local.exists() else Path(__file__).resolve().parent / "Samples.py"
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("user_climate_config", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载配置模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    configs = module.CONFIGS
    if not isinstance(configs, (list, tuple)) or not configs:
        raise ValueError("配置模块需要非空 CONFIGS 列表")
    return configs


def main(argv=None):
    parser = argparse.ArgumentParser(description="ERA5 / CMIP6 一键气候数据处理")
    parser.add_argument("--config", type=Path, help="配置 .py 文件，需定义 CONFIGS")
    parser.add_argument("--only", nargs="+", help="仅运行指定 name 的配置实例")
    parser.add_argument("--stages", nargs="+", choices=STAGES, help="覆盖阶段选择；总按流程顺序执行")
    parser.add_argument("--dry-run", action="store_true", help="只展示配置和路径，不读写数据")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        configs = load_configs(args.config)
        if args.only:
            missing = set(args.only) - {c.name for c in configs}
            if missing:
                raise ValueError(f"未找到配置: {sorted(missing)}")
            configs = [c for c in configs if c.name in args.only]
        for config in configs:
            if args.stages:
                config = replace(config, stages=tuple(args.stages))
            config.validate()
            if args.dry_run:
                LOG.info("%s enabled=%s stages=%s", config.name, config.enabled, config.stages)
                for key in ("root_path", "nc_folder", "tif_root", "daily_root", "monthly_root", "result_root", "mask_path"):
                    LOG.info("  %s: %s", key, getattr(config, key))
            else:
                run(config)
        return 0
    except Exception:
        LOG.exception("处理失败，请检查以上错误。已经完成的阶段输出会保留。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
