from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
from pprint import pformat
import sys
import time
import tomllib
from typing import Any, Sequence

from hytils import lightcyan, lightgreen, red
from .ext_packages import ExtPackages
from .ext_packages_install import download_install_ext_packages
from .parse_config import parse_config_
from .py_package import PyPackage
from .py_packages import PyPackages
from .backend_dirs import g_backend_dirs
from .logger import ilog



def install_app_packages(
    config_fp: Path | str,
    *,
    variants: Sequence[str] = ("", "lgpl"),
    keep_up_to_date: bool = True,
    reinstall: bool = False,
    threads: int = 1,
    use_local_rehost: bool = False,
    verbose: bool = False,
) -> bool:

    with open(Path(config_fp).resolve(), "rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    packages_cfg = parse_config_(data)

    # Update backend directories: no isolated python exe
    g_backend_dirs.python_exe = sys.executable
    ilog.debug(pformat(g_backend_dirs))


    # --- External packages --------------------------------------------------------------
    packages_to_install = ExtPackages(packages_cfg, sys.platform).filter_by_variant(
        variants=list(variants)
    )
    if packages_to_install:
        installed = download_install_ext_packages(
            packages=packages_to_install,
            reinstall=reinstall,
            threads=threads,
            use_local_rehost=use_local_rehost,
        )
        if not installed:
            ilog.error(red("Error: missing package(s)"))
            return False
        ilog.info(lightgreen("All external packages installed"))
    else:
        ilog.warning(lightgreen("No packages to install"))


    # --- Python packages ----------------------------------------------------------------
    ilog.info(lightgreen("Install additionnal python packages"))
    py_packages = PyPackages(
        packages_cfg,
        sys.platform,
        keep_up_to_date=keep_up_to_date
    )

    # hsys was installed in the fisrt round
    from hsys import is_feature_supported
    cuda = is_feature_supported('cuda')
    tensorrt = is_feature_supported('tensorrt')
    directml = is_feature_supported('directml')
    rocm = is_feature_supported('rocm')

    execution_providers = [
        f"CUDA: {'✅' if cuda else '❌'}",
        f"TensorRT: {'✅' if tensorrt else '❌'}",
        f"direct ML: {'✅' if directml else '❌'}",
        f"RocM: {'✅' if rocm else '❌'}",
    ]
    ilog.info(f"Supported execution providers\n  " + "\n  ".join(execution_providers))
    start_time = time.time()

    support = {
        "cuda": cuda,
        "rocm": rocm,
        "directml": directml,
        "cpu": not (cuda or tensorrt or rocm),  # fallback
    }
    for provider, supported in support.items():
        for pkg in py_packages.get_by_execution_provider(provider):
            pkg.skip = not supported
            pkg.supported = supported


    ilog.info("Supported packages:")
    supported_pkgs = py_packages.get_delayed(supported_only=True)
    for pkg in supported_pkgs:
        ilog.info(lightcyan(pkg.pretty_name))
        ilog.debug(pformat(pkg))

    # Fetch versions
    cpu_count = multiprocessing.cpu_count()
    cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))
    with ThreadPoolExecutor(max_workers=max(1, min(cpu_count, len(supported_pkgs)))) as executor:
        executor.map(lambda pkg: pkg.update_info(), supported_pkgs)
    elapsed = time.time() - start_time

    for pkg in supported_pkgs:
        pkg: PyPackage
        pkg_info = [
            f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}",
            f"      installed: {pkg.installed}",
            f"      variant: {pkg.variant}",
            f"      wheel: {pkg.wheel}",
            f"      wheel url: {pkg.wheel_url}",
            f"      size: {pkg.size // 1024}kB",
            f"      do cache: {pkg.do_cache}"
        ]
        ilog.debug("\n".join(pkg_info))
    ilog.debug(f" package versions updated in {elapsed:.02f}s")


    # --- Python packages to install -----------------------------------------------------
    uninstalled_pkgs = supported_pkgs.get_delayed().get_not_installed()
    if not uninstalled_pkgs:
        ilog.info(lightgreen("All python packages installed"))
        return True
    ilog.info(
        "Packages to install: "
        + ", ".join(lightcyan(f"{pkg.name} ({pkg.version})") for pkg in uninstalled_pkgs)
    )

    # Download if packages have to be cached
    for pkg in supported_pkgs:
        if pkg.installed or not pkg.do_cache:
            continue
        start_time = time.time()
        pkg.download_wheel(force=False, use_pip=False)
        elapsed = time.time() - start_time
        ilog.info(f"{pkg.name} downloaded in {elapsed:.02f}s")

    # Install packages
    for pkg in uninstalled_pkgs:
        pkg.install(reinstall=reinstall)


    # --- Verification -------------------------------------------------------------------

    py_packages.update_installed_versions()
    uninstalled_pkgs = supported_pkgs.get_delayed().get_not_installed()
    if not uninstalled_pkgs:
        for pkg in uninstalled_pkgs:
            ilog.critical(f"{pkg.name} not installed")
            pkg.install(recover=True)

    if uninstalled_pkgs:
        return False

    ilog.info(lightgreen("All python packages installed"))
    return True
