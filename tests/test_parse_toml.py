from pathlib import Path
from pprint import pprint
import signal
import sys
import tomllib
from typing import Any
from hytils import lightcyan, lightgreen
sys.path.append(str(Path(__file__).resolve().parent.parent))

from hinstall import (
    ilog,
    ExtPackages,
    parse_config_,
    PyPackages,
)



if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    tool = "hconvert"

    config_fp = (Path(__file__).parent / "configs" / f"{tool}.toml").resolve()
    print(f"loading config: {config_fp}")
    with open(config_fp, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    # load package toml cfg
    packages_cfg = parse_config_(data)

    print(lightgreen(" ".join(("-" * 40, "config", "-" * 40))))
    pprint(packages_cfg)


    if False:
        for platform_key in PLATFORMS:
            print(lightcyan(" ".join (("-" * 40, platform_key, "-" * 40))))
            packages = ExtPackages(packages_cfg, platform=platform_key)
            pprint(packages)
            print()

    if True:
        print(lightcyan(" ".join (("-" * 40, sys.platform, "-" * 40))))
        packages = ExtPackages(packages_cfg)
        pprint(packages)
        print()


    else:
        platform_key = sys.platform
        print(lightcyan(" ".join (("-" * 40, platform_key, "-" * 40))))
        packages = PyPackages(
            packages_cfg,
            # install_dir=g_backend_dirs.python_exe.parent,
            platform=platform_key,
            # section='py_packages',
        )
        print(lightcyan(" ".join (("-" * 40, "initial", "-" * 40))))
        pprint(packages.get_initial())
        print(lightcyan(" ".join (("-" * 40, "delayed", "-" * 40))))
        pprint(packages.get_delayed())
        pprint(packages.get_pypi_variant_names())
        print(lightcyan(" ".join (("-" * 40, "delayed", "-" * 40))))
        pprint(packages.get_by_variant("cuda"))
        print()
