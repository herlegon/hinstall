from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import Distribution, distributions
import json
import multiprocessing
from pathlib import Path
from pprint import pprint
import re
import subprocess
import sys
from typing import Any, Literal

from hytils import red, yellow

from .backend_dirs import g_backend_dirs
from .logger import ilog
from .py_package import PyPackage



HERLEGON_PACKAGES: tuple[str] = (
    'hutils',
    'hsys',
    'hwidgets',

    # backend is specific for each product,
    # the installation depends on the product name and is stored on the
    # herlegon github repo
    'hbackend',

    # pynnlib must always use the latest release: source only
    'pynnlib',
)

EXECUTION_PROVIDERS = ('cuda', 'rocm', 'directml', 'cpu')

def get_execution_provider(key: str) -> str:
    for ep in EXECUTION_PROVIDERS:
        if ep in key:
            return ep
        elif 'tensorrt' in key:
                return 'cuda'
        elif 'ncnn' in key:
                return 'cpu'
    return 'cpu'


class PyPackages(list):

    def __init__(
        self,
        config: dict = None,
        platform: str = "",
        keep_up_to_date: bool = False,
    ):
        super().__init__()
        if config:
            if not platform:
                platform = sys.platform
            self._parse_and_populate(config, platform, keep_up_to_date)


    def _parse_and_populate(self, config: dict, platform: str, keep_up_to_date: bool):
        platform_data = (
            config
            .get('py_packages', {})
            .get(platform, {})
            .get('default', {})
        )

        pretty_names: dict[str, str] = platform_data.get('names', {})

        # Process common packages: 1st pass
        common = platform_data.get('common', {})
        pattern = re.compile(
            r"^\s*([A-Za-z0-9_\-]+)\s*(==|>=|<=|>|<|!=)\s*([0-9a-zA-Z\.\-\+]+)\s*$"
        )
        if 'pypi' in common:
            for pkg_name in common['pypi']:
                version = ""
                if match := pattern.match(pkg_name):
                    pkg_name, op, version = match.groups()
                    # use latest version if more than
                    if ">" in op:
                        version = ""

                pretty_name = pretty_names.get(pkg_name, pkg_name)
                self.append(PyPackage(
                    pretty_name=pretty_name,
                    name=pkg_name,
                    version=version,
                ))

        # Process delayed packages
        delayed: dict[str, Any] = platform_data.get('delayed', {})
        property_keys: tuple[str] = (
            'extra_index_url',
            'index-url',
            'do_cache',
            'uninstall_before',
            'names',
            'skip',
        )

        for category, category_data in delayed.items():
            if not isinstance(category_data, dict):
                continue

            skip = category_data.get('skip', delayed.get('skip', False))
            extra_index_url = category_data.get('extra_index_url', delayed.get('extra_index_url', ''))
            index_url = category_data.get('index-url', delayed.get('index-url', ''))
            do_cache = category_data.get('do_cache', delayed.get('do_cache', False))
            uninstall_before = category_data.get('uninstall_before', delayed.get('uninstall_before', False))

            for key, value in category_data.items():
                key: str
                if key in property_keys:
                    continue
                if skip:
                    continue

                ep: str = get_execution_provider(key)

                # Handle nested structures (like torch with cpu/cuda/rocm variants)
                if isinstance(value, dict):
                    for variant, variant_data in value.items():
                        if variant in property_keys:
                            continue

                        skip = value.get('skip', skip)
                        variant_extra_index = value.get('extra_index_url', extra_index_url)
                        index_url = value.get('index-url', index_url)
                        do_cache = value.get('do_cache', do_cache)
                        uninstall_before = (
                            value.get(
                                'uninstall_before',
                                value.get('uninstall_before', uninstall_before)
                            )
                        )
                        if skip:
                            continue

                        variant: str
                        if not isinstance(variant_data, dict):
                            pkg_name, pkg_version = variant, variant_data

                            if pkg_name not in property_keys:
                                pretty_name = (
                                    pretty_names.get(
                                        f"{pkg_name}-{key}", pretty_names.get(pkg_name, pkg_name)
                                    )
                                    if key
                                    else pretty_names.get(pkg_name, pkg_name)
                                )
                                self.append(
                                    PyPackage(
                                        pretty_name=pretty_name,
                                        variant=key,
                                        name=pkg_name,
                                        version=pkg_version,
                                        extra_index_url=variant_extra_index,
                                        index_url=index_url,
                                        delayed_install=True,
                                        do_cache=do_cache,
                                        uninstall_before=uninstall_before,
                                        supported=False,
                                        skip=skip,
                                        ep=ep,
                                    )
                                )

                else:
                    # Simple key-value pair
                    pkg_name = key
                    pretty_name = pretty_names.get(pkg_name, pkg_name)
                    self.append(
                            PyPackage(
                            pretty_name=pretty_name,
                            name=key,
                            version=value,
                            extra_index_url=extra_index_url,
                            index_url=index_url,
                            delayed_install=True,
                            do_cache=do_cache,
                            supported=False,
                            skip=skip,
                            ep=ep,
                        )
                    )

        if keep_up_to_date:
            self.update_latest_versions()
        self.update_installed_versions()


    @staticmethod
    def get_pkg_info(d: Distribution):
        try:
            if direct_url := d.read_text('direct_url.json'):
                info: dict[str, str] = json.loads(direct_url)
                if info.get('dir_info', {}).get('editable'):
                    return {"version": d.version, "location": info.get('url', '').replace('file://', '')}
        except (FileNotFoundError, TypeError):
            pass
        return {"version": d.version}


    def update_installed_versions(self) -> None:
        packages_versions: dict[str, str] = {}

        python_exe = str(g_backend_dirs.python_exe)
        if sys.executable != python_exe:
            embedded_script = (Path(__file__).parent / "get_versions.py").resolve()
            try:
                result = subprocess.run(
                    [str(python_exe), str(embedded_script)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                packages_versions = json.loads(result.stdout)

            except subprocess.CalledProcessError as e:
                # Specific error if subprocess fails
                ilog.error(f"Error occurred while updating pip: {str(e)}")

            except Exception as e:
                # Catch all other unexpected errors
                ilog.error(f"Unexpected error while fetching installed python packages: {str(e)}")

        else:
            # Doesn't work if this function is not executed in standalone env
            packages_versions = {d.name: self.get_pkg_info(d) for d in distributions()}

        if packages_versions:
            for pkg in self:
                pkg: PyPackage
                version = packages_versions.get(pkg.name, pkg.installed_version)
                if isinstance(version, dict):
                    if 'location' in version:
                        version = 'dev'
                    else:
                        version = version.get('version', pkg.installed_version)
                if version:
                    pkg.installed_version = version
                pkg.installed = True if pkg.installed_version else False


    def update_latest_versions(self) -> None:
        cpu_count = multiprocessing.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))
        with ThreadPoolExecutor(max_workers=max(1, min(cpu_count, len(self)))) as executor:
            executor.map(lambda pkg: pkg.update_info(), self)


    def get_initial(self) -> 'PyPackages':
        result = PyPackages()
        result.extend([pkg for pkg in self if not pkg.delayed_install])
        return result


    def get_delayed(self, supported_only: bool = False) -> 'PyPackages':
        """Get all packages marked for delayed installation."""
        result = PyPackages()
        if supported_only:
            result.extend([pkg for pkg in self if pkg.delayed_install and pkg.supported])
        else:
            result.extend([pkg for pkg in self if pkg.delayed_install])

        return result


    def get_pypi_variant_names(self) -> list[str]:
        """Get a list of all package names."""
        names: list[str] = []
        for pkg in self:
            pkg: PyPackage
            names.append(
                f"{pkg.name}-{pkg.variant}" if pkg.variant else pkg.name
            )
        return names


    def get_by_execution_provider(
        self,
        execution_provider: Literal['cpu', 'cuda', 'rocm', 'directml']
    ) -> list[PyPackage]:
        return [pkg for pkg in self if pkg.ep == execution_provider]


    def get_by_variant(
        self,
        variant: Literal['cpu', 'cuda', 'rocm', 'directml']
    ) -> list[PyPackage]:
        return [pkg for pkg in self if pkg.variant == variant]


    def get_installed(self) -> 'PyPackages':
        """Get all installed packages."""
        result = PyPackages()
        result.extend([pkg for pkg in self if pkg.installed])
        return result


    def get_not_installed(self) -> 'PyPackages':
        """Get all packages that are not installed."""
        result = PyPackages()
        result.extend([pkg for pkg in self if not pkg.installed])
        return result


    def get_outdated(self) -> 'PyPackages':
        """Get packages where installed version doesn't match required version."""
        result = PyPackages()
        result.extend([pkg for pkg in self if pkg.installed and not pkg.is_installed()])
        return result


    def get_to_uninstall(self) -> 'PyPackages':
        """Get packages marked to uninstall before installing."""
        result = PyPackages()
        result.extend([pkg for pkg in self if pkg.uninstall_before])
        return result


    def find(self, **kwargs) -> 'PyPackages':
        """
        Find packages matching specific criteria.

        Example:
            packages.find(name='torch', delayed_install=True)
            packages.find(installed=False, version='2.9.0+cpu')
        """
        result = PyPackages()
        for pkg in self:
            if all(getattr(pkg, key, None) == value for key, value in kwargs.items()):
                result.append(pkg)
        return result
