from pathlib import Path
from pprint import pprint
import signal
import sys
import tomllib
from typing import Any

from hytils import lightcyan, lightgreen, red
sys.path.append(str(Path(__file__).resolve().parent.parent))

from hinstall import (
    parse_config_,
    ExtPackages,
    download_install_ext_packages,
    g_backend_dirs,
)
from local_rehost import get_rehost_dir


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    tool = "hconvert"

    config_fp = (Path(__file__).parent / "configs" / f"{tool}.toml").resolve()
    print(f"loading config: {config_fp}")
    with open(config_fp, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    packages_cfg = parse_config_(data)
    external_packages = ExtPackages(packages_cfg, sys.platform)

    g_backend_dirs.local_rehost = get_rehost_dir()

    python_package = external_packages.get_by_key('python')
    print(lightcyan(" ".join (("-" * 40, "python", "-" * 40))))
    pprint(python_package)
    print()

    if python_package:
        installed: bool = download_install_ext_packages(
            packages=python_package,
            reinstall=True,
            threads=1,
            use_local_rehost=True
        )
        if installed:
            print(lightgreen("Python package installed"))
        else:
            print(red("Error: python not installed"))
    else:
        print(red("Error: no package to install"))
