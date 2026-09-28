from concurrent.futures import ThreadPoolExecutor
from .backend_dirs import g_backend_dirs
from .ext_package import ExtPackage
from .logger import ilog



def download_package_(
    package: ExtPackage,
    reinstall: bool = False,
) -> ExtPackage:

    if not reinstall and package.is_up_to_date():
        package.clean_cache()
        return package

    if not reinstall and package.is_installed(up_to_date=False):
        if not package.do_cache:
            try:
                package.cache_file.unlink()
            except:
                pass
        package.clean_cache()
        return package


    # Dowanload an install
    package.installed = False
    is_cached = package.is_cached()

    # Use local host to simulate a download
    package.downloaded = False
    if (
        not is_cached
        and package.use_local_rehost
        and g_backend_dirs.local_rehost
    ):
        package.download_from_local_rehost()

    # Finally download it from host
    if not package.downloaded:
        package.download_from_host()

    return package



def dl_and_install_ext_package(
    package: ExtPackage,
    reinstall: bool = False,
) -> bool:
    if package.skip:
        return True
    ilog.info(f"{package.name}")

    package = download_package_(package, reinstall=reinstall)

    # Install package
    if not package.installed or reinstall:
        package.install()

    if package.installed:
        ilog.status(f"Installed {package.name}.")
    else:
        ilog.error(f"{package.name}: failed to install")

    return package.installed



def download_install_ext_packages(
    packages: list[ExtPackage] | ExtPackage,
    retry: int = 3,
    threads: int = 1,
    reinstall: bool = False,
    use_local_rehost: bool = False,
) -> bool:
    """Entry point to install packages.
    Use only a single thread when used with GUI because of progress bar
    """

    if isinstance(packages, list):
        packages = [package for package in packages if not package.skip]
    else:
        packages = (
            [packages]
            if not packages.skip
            else []
        )

    if use_local_rehost and g_backend_dirs.local_rehost is None:
        ilog.error("g_backend_dirs.local_rehost shall be set before downloading")
        return False

    for pkg in packages:
        pkg.use_local_rehost = use_local_rehost
        pkg.retry_count = retry

    threads = min(max(threads, 1), len(packages))
    if threads == 1:
        for package in packages:
            success = dl_and_install_ext_package(
                package=package,
                reinstall=reinstall,
            )
            if not success:
                return False
    else:
        success: bool = True
        with ThreadPoolExecutor(max_workers=threads) as executor:
            for result in executor.map(
                lambda args: dl_and_install_ext_package(**args),
                [
                    {
                        'package': package,
                        'reinstall': reinstall
                    }
                    for package in packages
                ]
            ):
                success = success and result
        return success

    return True



