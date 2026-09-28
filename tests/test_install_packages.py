import argparse
import logging
from pathlib import Path
from pprint import pformat
import signal
import sys
import tomllib
from typing import Any

from hytils import lightcyan, lightgreen, red
from local_rehost import get_rehost_dir

sys.path.append(str(Path(__file__).resolve().parent.parent))
from hinstall import (
    parse_config_,
    ExtPackages,
    PACKAGES,
    g_backend_dirs,
    download_install_ext_packages,
    ilog,
)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    ilog.setLevel(logging.INFO)

    parser = argparse.ArgumentParser(description="Download and install external packages.")
    parser.add_argument(
        "package",
        nargs="?",
        default="ffmpeg",
        choices=PACKAGES,
        help=f"Package to install (choices: {', '.join(PACKAGES)})",
    )
    args = parser.parse_args()
    tool = args.package

    config_fp = (Path(__file__).parent / "configs" / f"{tool}.toml").resolve()
    if not config_fp.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_fp}")

    ilog.info(f"loading config: {config_fp}")
    with open(config_fp, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    ilog.info(lightcyan(" ".join (("-" * 40, "Parsed TOML", "-" * 40))))
    packages_cfg = parse_config_(data)
    ilog.info(pformat(packages_cfg))

    g_backend_dirs.local_rehost = get_rehost_dir()
    ilog.info(lightcyan(" ".join (("-" * 40, "backend directories", "-" * 40))))
    ilog.info(pformat(g_backend_dirs))

    external_packages = ExtPackages(packages_cfg, sys.platform)
    ilog.info(lightcyan(" ".join (("-" * 40, "External packages", "-" * 40))))
    ilog.info(pformat(external_packages))

    # All except python
    packages_to_install = (
        external_packages
        # .get_all_except('python')
        .filter_by_variant(variants=["", "lgpl"])
    )
    ilog.info(lightcyan(" ".join (("-" * 40, f"{sys.platform}, to install", "-" * 40))))
    ilog.info(pformat(packages_to_install))


    if packages_to_install:
        installed: bool = download_install_ext_packages(
            packages=packages_to_install,
            reinstall=True,
            threads=1,
            use_local_rehost=False,
        )
        if installed:
            ilog.info(lightgreen("All packages installed"))
        else:
            ilog.info(red("Error: missing package(s)"))
    else:
        ilog.info(lightgreen("No packages to install"))


