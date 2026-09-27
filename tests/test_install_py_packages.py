from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
from pprint import pprint
import re
import signal
import subprocess
import sys
import time
import tomllib
from typing import Any

from hytils import lightcyan, lightgreen, red, yellow
from local_rehost import get_rehost_dir

sys.path.append(str(Path(__file__).resolve().parent.parent))
from hinstall import (
    parse_config_,
    ExtPackages,
    PyPackages,
    PyPackage,
    g_backend_dirs,
    download_install_ext_packages,
    generate_backend_env,
    get_python_version,
    ilog,
    clean_invalid_distributions,
)



if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    tool = "hconvert"

    config_fp = (Path(__file__).parent / "configs" / f"{tool}.toml").resolve()
    print(f"loading config: {config_fp}")
    with open(config_fp, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    packages_cfg = parse_config_(data)

    # Install python if not yest installed
    python_package = ExtPackages(packages_cfg, sys.platform).get_by_key('python')
    pprint(python_package)

    # Use local rehost
    g_backend_dirs.local_rehost = get_rehost_dir()
    python_package.use_local_rehost = True

    if not python_package.is_installed():
        ilog.error(f"{python_package.name} is not installed. Installing...")
        installed: bool = download_install_ext_packages(
            packages=python_package,
            reinstall=False,
            use_local_rehost=True
        )
        if not python_package.installed:
            ilog.error(f"Error: {python_package.name} not installed")
            sys.exit(-1)
    else:
        ilog.info(f"{python_package.name} is installed.")

    backend_env = generate_backend_env()

    clean_invalid_distributions()


    # Python packages
    keep_up_to_date: bool = False
    # g_backend_dirs.python_exe = "python"

    py_packages = PyPackages(
        packages_cfg,
        sys.platform,
        keep_up_to_date=keep_up_to_date
    )

    # Display the package sthat have to be installed first
    if False:
        py_packages = py_packages.get_initial()

    # Python version
    ilog.info(get_python_version())

    # List uninstalled python packages
    if False:
        uninstalled_pkgs = py_packages.get_not_installed()
        print("uninstalled")
        pprint(uninstalled_pkgs)

    # get_pypackage_list()
    # update_package_info(py_packages[0])



    # Update wheels
    if False:
        uninstalled_pkgs = py_packages.get_delayed().get_not_installed()
        pprint(f"get wheel url")
        for pkg in uninstalled_pkgs:
            pkg: PyPackage
            pkg.update_wheel_url()
        pprint(uninstalled_pkgs)

    if False:
        # uninstalled_packages = py_packages.get_initial().get_not_installed()
        uninstalled_pkgs = py_packages.get_not_installed()
        for pkg in uninstalled_pkgs:
            pkg: PyPackage
            if (
                pkg.variant in 'cuda'
                or pkg.name == 'tensorrt'
                or not pkg.delayed_install
            ):
                pkg.fetch_latest_version()
                print(f"{pkg.name}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
                print(f"    variant: {pkg.variant}")
                start_time = time.time()
                pkg.update_info()
                print(f"    wheel: {pkg.wheel}")
                print(f"    size: {pkg.size}")


    initial_pkgs = py_packages.get_initial()
    uninstalled_pkgs = initial_pkgs.get_not_installed()
    delayed_pkgs = py_packages.get_delayed()

    if True:
        cpu_count = multiprocessing.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))


        selected_pkgs = uninstalled_pkgs
        if selected_pkgs:

            start_time = time.time()
            if False:
                for pkg in selected_pkgs:
                    pkg: PyPackage
                    pprint(pkg)
                    pkg.update_info()
            else:
                with ThreadPoolExecutor(max_workers=min(cpu_count, len(selected_pkgs))) as executor:
                    executor.map(lambda pkg: pkg.update_info(), selected_pkgs)

            elapsed = time.time() - start_time
            for pkg in selected_pkgs:
                pkg: PyPackage
                print(f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
                print(f"    variant: {pkg.variant}")
                print(f"    installed version: {pkg.installed_version}")
                print(f"    wheel: {pkg.wheel}")
                print(f"    wheel url: {pkg.wheel_url}")
                print(f"    size: {pkg.size // 1024}kB")
            ilog.info(f"updated in {elapsed:.02f}s")

        # sys.exit()

    # sys.exit()

    python_exe = str(g_backend_dirs.python_exe)
    cache_dir = str(g_backend_dirs.cache)
    # Cache only the big packages
    print(f"Cache: {cache_dir}")
    print("Packages to install: ", lightcyan(", ".join((pkg.name for pkg in uninstalled_pkgs))))

    do_download = True
    for pkg in uninstalled_pkgs:
        if pkg.size > 50000:
            pkg.do_cache = True

        if do_download and pkg.do_cache:
            start_time = time.time()
            downloaded = pkg.download_wheel(force=False, use_pip=False)
            elapsed = time.time() - start_time
            ilog.debug(f"Downloaded {pkg.name} in {elapsed:.02f}s")

        pkg.install(force=False)



    from hsys import is_feature_supported

    cuda = is_feature_supported('cuda')
    tensorrt = is_feature_supported('tensorrt')
    directml = is_feature_supported('directml')
    rocm = is_feature_supported('rocm')

    print(f"CUDA: {'✅' if cuda else '❌'}")
    print(f"TensorRT: {'✅' if tensorrt else '❌'}")
    print(f"direct ML: {'✅' if directml else '❌'}")
    print(f"RocM: {'✅' if rocm else '❌'}")

    start_time = time.time()


    for pkg in py_packages.get_by_execution_provider('cuda'):
        pkg.skip = not cuda
        pkg.supported = cuda

    for pkg in py_packages.get_by_execution_provider('rocm'):
        pkg.skip = not rocm
        pkg.supported = rocm

    for pkg in py_packages.get_by_execution_provider('directml'):
        pkg.skip = not directml
        pkg.supported = directml

    cpu_fallback = all([x is False for x in (cuda, tensorrt, rocm)])
    for pkg in py_packages.get_by_execution_provider('cpu'):
        pkg.skip = not cpu_fallback
        pkg.supported = cpu_fallback


    print("supported packages")
    supported_pkgs = py_packages.get_delayed(supported_only=True)
    for pkg in supported_pkgs:
        print(lightcyan(pkg.pretty_name))
        pprint(pkg)

    with ThreadPoolExecutor(max_workers=min(cpu_count, len(supported_pkgs))) as executor:
        executor.map(lambda pkg: pkg.update_info(), supported_pkgs)
    elapsed = time.time() - start_time

    for pkg in supported_pkgs:
        pkg: PyPackage
        print(f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
        print(f"    installed: {pkg.installed}")
        print(f"    variant: {pkg.variant}")
        print(f"    wheel: {pkg.wheel}")
        print(f"    wheel url: {pkg.wheel_url}")
        print(f"    size: {pkg.size // 1024}kB")
        print(f"    do cache: {pkg.do_cache}")
    ilog.info(f"updated in {elapsed:.02f}s")


    print("Packages to install: ", lightcyan(", ".join((pkg.name for pkg in uninstalled_pkgs))))


    for pkg in supported_pkgs:
        if pkg.installed or not pkg.do_cache:
            continue

        start_time = time.time()
        downloaded = pkg.download_wheel(force=False, use_pip=False)
        elapsed = time.time() - start_time
        ilog.info(f"{pkg.name} downloaded in {elapsed:.02f}s")
        print(lightcyan("-" * 80))

    for pkg in supported_pkgs:
        if pkg.installed:
            continue
        pkg.install(reinstall=False)


    py_packages.update_installed_versions()
    for pkg in supported_pkgs:
        if not pkg.installed:
            ilog.critical(f"{pkg.name} not installed")
            pkg.install(recover=True)

