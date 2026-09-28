from dataclasses import dataclass, field
import io
from pathlib import Path
import platform
from pprint import pprint
import re
import shutil
import sysconfig
import tempfile
import time
from typing import Callable, Literal, Optional
import requests
import subprocess
import sys
from urllib.parse import quote

from .wheel_format import (
    filter_compatible_wheels, get_platform_tags, get_python_tags,
)
from hytils import lightcyan, lightgreen, red, yellow

from .logger import ilog
from .backend_dirs import g_backend_dirs, get_local_dev_dir
from .py_packages_install import (
    generate_backend_env,
)
try:
    from hwss.api import InstallProgress
except ImportError:
    from .api import InstallProgress


@dataclass
class PyPackage:
    pretty_name: str
    name: str
    variant: str = ""
    skip: bool = False

    # version to install, installed and latest from pypi
    version: str = ""
    _installed_version: str = ""
    latest_version: str = ""

    extra_index_url: str = ""
    index_url: str = ""

    wheel: str = ""
    wheel_url: str = ""
    size: int = 0
    supported: bool = True
    installed: bool = False
    uninstall_before: bool = False
    delayed_install: bool = False
    do_cache: bool = False

    _retry_count: int = 3

    # Optional callback for progress updates
    progress_callback: Optional[Callable[[str, str], None]] = field(default=None, repr=False)

    # Optional callback for log messages (type, text)
    message_callback: Optional[Callable[[str, str], None]] = field(default=None, repr=False)

    # Execution provider
    ep: Literal['cuda', 'rocm', 'directml', 'cpu'] = ''


    @property
    def retry_count(self) -> int:
        return self._retry_count


    @retry_count.setter
    def retry_count(self, count: int) -> None:
        self._retry_count = count


    @property
    def installed_version(self) -> str:
        return self._installed_version


    @installed_version.setter
    def installed_version(self, version: str) -> None:
        self._installed_version = version
        # Do not allow downgrading.
        # if really needed, reinstall a new python package.
        local_versions = ('dev', 'local')
        if (
            self.version in local_versions
            or self._installed_version in local_versions
            or self.is_downgrading()
        ):
            self.version = self._installed_version
            self.installed = True


    def resolve_tensorrt_wheel(self) -> bool:
        """Resolve the best TensorRT wheel from NVIDIA's simple index."""

        import requests
        from html.parser import HTMLParser

        index_url = f"{self.index_url}/{self.name.replace('_', '-')}/"
        # ilog.debug(f"index_url: {index_url}")

        # Fetch HTML index
        try:
            response = requests.get(index_url, timeout=10)
            response.raise_for_status()
        except Exception as e:
            ilog.error(f"[TensorRT] Failed to fetch index: {e}")
            return False

        # --- Parse links from simple HTML page ---
        class LinkParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag != "a":
                    return
                for k, v in attrs:
                    if k == "href":
                        clean_href = v.split("#")[0]
                        fname = clean_href.split("/")[-1]
                        self.links.append(fname)

        parser = LinkParser()
        parser.feed(response.text)

        # Collect all wheels for this version
        wheels = []
        target_version = self.version

        # ilog.debug(f"\n  ".join(parser.links))
        for href in parser.links:
            fname = href.split("/")[-1]
            if fname.endswith(".whl") and target_version in fname:
                wheels.append({
                    "filename": fname,
                    "url": href if href.startswith("http") else index_url + href,
                })

        if not wheels:
            # ilog.error(f"{self.name} No wheels found for version {self.version}")
            return False

        matches = filter_compatible_wheels(wheels)
        if not matches:
            ilog.error(f"{self.name} No compatible wheel found for your platform.")
            return False

        best = matches[0]
        self.wheel = best["filename"]
        self.wheel_url = best["url"]
        self.supported = True
        self.size = self.get_wheel_size()

        return True


    def uninstall(self) -> bool:
        ilog.debug(f"{self.name} uninstall")
        python_exe = str(g_backend_dirs.python_exe)

        pip_command: str = f"{python_exe} -m pip uninstall -y {self.name}"
        try:
            result = subprocess.run(
                pip_command.split(' '),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            result_str = result.stdout.strip()

        except Exception as e:
            ilog.error(f"Unexpected error while uninstalling packages: {str(e)}")
            return False

        ilog.debug(result_str)
        return True


    def is_downgrading(self) -> bool:
        if not self.version or not self.installed_version:
            return False

        def _parse_version(v: str):
            """Turn version strings into a list of integers."""
            # Remove any non-numeric suffixes like .post1 or +rocm6.4
            v = re.sub(r'(\.post\d+|[\+\-].*)', '', v)
            return [int(x) for x in v.split(".")]

        to_install = _parse_version(self.version)
        current = _parse_version(self.installed_version)

        # Extend lists to equal length (e.g., 1.2 vs 1.2.0)
        length = max(len(current), len(to_install))
        current.extend([0] * (length - len(current)))
        to_install.extend([0] * (length - len(to_install)))

        is_downgrading = current > to_install
        if is_downgrading:
            ilog.error(f"Downgrading is not permitted: {self.installed_version} -> {self.version}")

        return is_downgrading


    def _update_wheel_info(self, wheel_file: dict) -> None:
        self.wheel = wheel_file['filename']
        self.wheel_url = wheel_file['url']
        self.size = wheel_file['size']


    def fetch_info_from_pypi(self) -> bool:
        try:
            url = f"https://pypi.org/pypi/{self.name}/json"
            response = requests.get(url, timeout=5)
            if response.status_code != 200:
                ilog.error(f"package: status code: {response.status_code}")
                raise ValueError(f"package")

        except Exception as e:
            ilog.error(f"Exception: {str(e)}")
            raise ValueError("package")

        data = response.json()
        info = data['info']
        # pprint(info)

        # Update latest version
        self.latest_version = info["version"]

        # Update wheel
        version = self.version if self.version else self.latest_version
        if not version:
            ilog.error(f"{self.name}: no version found")
            return False

        if 'torch' in self.name or 'tensorrt' in self.name:
            return True

        if version and version not in data['releases'].keys():
            ilog.error(f"{self.name}: no version found in pypi releases")
            raise ValueError("version")

        if sys.platform == 'win32' and False:
            # Get platform-specific details
            platform_tag: str = get_platform_tags()


            # Look for a wheel file that matches the platform, Python version, and architecture
            files = []
            for f in data['releases'][version]:
                filename: str = f['filename']
                if (
                    filename.endswith('.whl')
                    and (
                        platform_tag in filename or "-any" in filename
                    )
                ):
                    files.append(f)


            if not files:
                # pprint(data['releases'][version])
                print(red(f"{self.name}: no files"))
                print(platform_tag)
                for f in data['releases'][version]:
                    print(f['filename'])
                raise ValueError("wheel")

            if len(files) == 1:
                self._update_wheel_info(files[0])
                return True

            # Find the minimum python version
            py_prefix = list(set([f['python_version'][:2] for f in files]))

            if "cp" in py_prefix:
                py_versions = sorted(
                    list(set([
                        int(f['python_version'][2:])
                        for f in files
                        if f['python_version'][:2] == 'cp'
                    ]))
                )
            elif "py" in py_prefix:
                py_versions = set()
                version_pattern = r'cp(\d{3})'
                for f in files:
                    versions = re.findall(version_pattern, f['filename'])
                    py_versions.update(versions)
                py_versions = sorted(list(map(int, py_versions)))

            else:
                ilog.error(f"py_prefix not supported")
                raise ValueError("wheel")

            current_version = sys.version_info.major * 100 + sys.version_info.minor
            if current_version in py_versions:
                highest_supported_version = current_version

            elif len(py_versions) == 1:
                if current_version != py_versions[0]:
                    ilog.error(f"{self.name} only a single version found")

                    print(red(f"{self.name}: one remaining but incompatible"))
                    raise ValueError("wheel")
            else:
                highest_supported_version = None
                for v in py_versions:
                    if v <= current_version:
                        highest_supported_version = v
                if not highest_supported_version:
                    print(red(f"{self.name}: one remaining but incompatible"))
                    raise ValueError("wheel")
            version_filter = f"cp{highest_supported_version}"
            files = [f for f in files if version_filter in f['filename']]


            if len(files) == 1:
                self._update_wheel_info(files[0])
                return True


        else:
            files = filter_compatible_wheels(data['releases'][version])
            if files is None or not files:
                ilog.debug(f"python_tags: {get_python_tags()}")
                ilog.debug(f"platform_tags: {get_platform_tags()}")
                for f in data['releases'][version]:
                    ilog.debug(f"    {f['filename']}")
                ilog.error(f"{self.name} failed filtering files")
                raise ValueError("wheel")

            self._update_wheel_info(files[0])
            return True

        print(red(f"{self.name} No compatible wheel file found"))
        # pprint(self)
        # pprint(files)
        # pprint(data['releases'][version])
        raise ValueError(f"{self.name} No compatible wheel file found")
        return True


    def get_wheel_size(self) -> int:
        if not self.wheel_url:
            return 0

        self.size = 0
        try:
            # HEAD request avoids downloading the file
            response = requests.head(
                self.wheel_url,
                stream=True,
                allow_redirects=True,
                timeout=5
            )
            if response.status_code == 200:
                size = int(response.headers.get("content-length", 0))

            else:
                ilog.error(f"Failed to get wheel size, status code: {response.status_code}")

        except Exception as e:
            ilog.error(f"exception while getting size: {str(e)}")

        return size


    def resolve_torch_wheel(self):
        """
        Determine the correct PyTorch wheel URL and size.
        If version is not set, use latest PyTorch version from PyPI.
        Handles URL encoding for '+' in wheel filenames.
        """
        try:
            # Step 1: Use latest version if none specified
            version = self.version if self.version else self.latest_version
            if not version:
                self.fetch_latest_version()
                version = self.version if self.version else self.latest_version
            if not version:
                ilog.error("No PyTorch version specified or found")
                return

            # Step 2: Python version
            python_version = f"{sys.version_info.major}{sys.version_info.minor}"

            # Step 3: Detect architecture
            sys_platform = sys.platform
            if sys_platform.startswith("win"):
                arch = "win_amd64" if platform.architecture()[0] == "64bit" else "win32"
            elif sys_platform == "darwin":
                arch = "arm64" if platform.machine() == "arm64" else "x86_64"
            elif sys_platform.startswith("linux"):
                arch = "manylinux_2_28_x86_64"  # default Linux x86_64
            else:
                arch = "unknown"

            # arch = "win_amd64"
            # Step 4: Construct wheel filename
            self.wheel = f"{self.name}-{version}-cp{python_version}-cp{python_version}-{arch}.whl"

            # URL encode '+' in the version string
            if '+' in version:
                version, compute_platform = version.split('+')
            else:
                compute_platform = 'cpu'

            wheel_url = f"https://download.pytorch.org/whl/{compute_platform}/{quote(self.wheel)}"

            # Step 5: Check wheel existence (HEAD request)
            response = requests.head(wheel_url, allow_redirects=True, timeout=10)
            if response.status_code == 200:
                self.size = int(response.headers.get("content-length", 0))
                self.wheel_url = wheel_url
                self.wheel = self.wheel
                return True
            else:
                ilog.error(f"Wheel not found: {wheel_url}, status: {response.status_code}")
                return

        except Exception as e:
            ilog.error(f"Error resolving PyTorch wheel: {str(e)}")
            return


    def update_info(self):
        if 'torch' in self.name:
            self.resolve_torch_wheel()

        elif 'tensorrt' in self.name:
            self.resolve_tensorrt_wheel()
            return

        elif self.version == 'dev':
            ilog.info(f"{self.name} use local repo used for dev")
            return

        else:
            try:
                self.fetch_info_from_pypi()

            except Exception as e:
                exception = str(e)
                if 'version' in exception:
                    # Version not found, use latest
                    ilog.error(f"Version not found for {self.name}, use latest")
                    self.version = ""
                    self.update_info()

                elif 'wheel' in exception:
                    ilog.critical(f"Wheel not found for {self.name}")

                elif 'package' in exception:
                    ilog.critical(f"Package {self.name} not found on pypi")

                return


    def send_end_progress(self, status: Literal['success', 'failed']) -> None:
        # Whatever the type, it will
        ilog.progress(
            InstallProgress(
                package_name=self.name,
                status=status,
                type='indet',
                progress=100,
            )
        )


    def send_update_progress(self, progress: float) -> None:
        ilog.progress(
            InstallProgress(
                package_name=self.name,
                type='progress',
                progress=progress,
            )
        )


    def _download_wheel_with_pip(self, force: bool = False) -> bool:
        ilog.debug(f"{self.name} use pip to download wheel")
        ilog.progress(
            InstallProgress(
                package_name=self.name,
                status='',
                type='indet',
                progress=0,
            )
        )

        python_exe = str(g_backend_dirs.python_exe)
        cache_dir: Path = g_backend_dirs.cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        wheel_fp: Path = cache_dir / self.wheel

        pnv = "==".join((self.name, self.version)) if self.version else self.name

        cmd = f"{python_exe} -m pip download -d {str(cache_dir)} --no-deps {pnv}"
        if self.extra_index_url:
            cmd = f"{cmd} --extra-index-url={self.extra_index_url}"
        if self.index_url:
            cmd = f"{cmd} --index-url={self.index_url}"

        if force:
            wheel_fp.unlink(missing_ok=True)
            cmd = f"{cmd} --no-cache-dir"

        ilog.debug(cmd)

        env = generate_backend_env(exclude_append=['proxy',])
        try:
            result = subprocess.run(
                cmd.split(),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            # Check if 'Successfully installed' is in the output
            if "Successfully downloaded" in result.stdout.splitlines()[-1]:
                ilog.info(f"{self.name} successfully downloaded")
                self.send_end_progress(status='success')
                return True

            else:
                ilog.error(f"{self.name} download failed: {result.stdout}")

        except subprocess.CalledProcessError as e:
            ilog.critical(f"{self.name} failed to downloaded package {e.stderr}")

        except Exception as e:
            ilog.critical(f"{self.name} download encountered an error: {str(e)}")

        self.send_end_progress(status='failed')
        return False


    @staticmethod
    def format_time(seconds: float) -> str:
        """Format seconds to human readable time"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"


    def get_cache_dir(self) -> Path:
        if self.do_cache:
            return g_backend_dirs.cache
        else:
            return  Path(tempfile.gettempdir()) / "herlegon"


    def download_from_local_rehost(self) -> bool:
        downloaded: bool = False

        if g_backend_dirs.local_rehost is None:
            ilog.debug(f"Local rehost doesn't exist: {g_backend_dirs.local_rehost}")
            return False

        local_fp: Path = g_backend_dirs.local_rehost / self.wheel
        cache_dir = self.get_cache_dir()
        ilog.debug(f"Download {self.name} from local host: {local_fp} to {cache_dir}")

        # Copy from local rehost to cache
        if local_fp.exists() and self.do_cache:
            shutil.copy(local_fp, cache_dir)
            downloaded = True

        else:
            ilog.debug(f"Wheel not found on local rehost")

        return downloaded


    def _download_wheel_with_requests(
        self,
        force: bool = False,
        stall_timeout: float = 30,
    ) -> bool:
        ilog.debug(f"Use requests to download wheel: {self.name}")
        wheel_fp: Path = self.get_cache_dir() / self.wheel

        try:
            response = requests.get(
                self.wheel_url,
                stream=True,
                timeout=10,
                allow_redirects=True
            )
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            if total_size == 0:
                ilog.warning(f"Unknown file size for {self.wheel}")

            if (
                not force
                and wheel_fp.is_file()
                and wheel_fp.stat().st_size == total_size
            ):
                ilog.debug(f"Wheel already downloaded.")
                self.downloaded = True
                return True

            # Not already downloaded
            ilog.info(f"Downloading {self.wheel} from {self.wheel_url}")
            downloaded = 0
            start_time = time.time()
            last_log_time = start_time

            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='',
                    type='progress',
                    progress=0,
                )
            )
            with open(wheel_fp, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        last_data_time = time.time()

                        # Log progress every 0.5 seconds to avoid spam
                        current_time = time.time()
                        if current_time - last_log_time >= 1 and total_size > 0:
                            percentage = (downloaded / total_size) * 100
                            size_mb = downloaded / (1024**2)
                            total_mb = total_size / (1024**2)
                            elapsed = current_time - start_time

                            # Calculate speed
                            speed_mbps = (downloaded / (1024**2)) / elapsed if elapsed > 0 else 0

                            # Estimate time remaining
                            if speed_mbps > 0:
                                remaining_mb = total_mb - size_mb
                                eta_seconds = remaining_mb / speed_mbps
                                eta_str = self.format_time(eta_seconds)
                            else:
                                eta_str = "calculating..."

                            ilog.debug(f"Downloaded {size_mb:.1f}/{total_mb:.1f} MB | {speed_mbps:.1f} MB/s | ETA: {eta_str}")
                            self.send_update_progress(progress=percentage)
                            last_log_time = current_time

                else:
                    # Empty chunk - check for stall
                    if time.time() - last_data_time > stall_timeout:
                        raise requests.exceptions.Timeout(
                            f"Download stalled: no data received for {stall_timeout}s"
                        )

            elapsed = time.time() - start_time
            speed_mbps = (downloaded / (1024**2)) / elapsed if elapsed > 0 else 0
            ilog.info(f"Downloaded {self.wheel} ({downloaded / (1024**2):.1f} MB in {self.format_time(elapsed)} at {speed_mbps:.1f} MB/s)")
            self.send_end_progress(status='success')
            return True

        except requests.exceptions.RequestException as e:
            ilog.error(f"Download failed: {str(e)}")
            # Clean up partial file
            wheel_fp.unlink(missing_ok=True)

        except Exception as e:
            ilog.critical(f"Unexpected error downloading {self.wheel}: {str(e)}")
            wheel_fp.unlink(missing_ok=True)

        self.send_end_progress(status='failed')
        return False


    def download_wheel(
        self,
        force: bool = False,
        stall_timeout: float = 10,
        use_pip: bool = False,
        use_local_rehost: bool = False
    ) -> bool:
        downloaded: bool = False

        # If no cache, will be downloaded by pip
        if not self.do_cache:
            return True

        # No need to download when in dev mode
        if self.version in ('dev', 'local'):
            return True

        cache_dir = self.get_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        # If no wheel found or force download with pip
        wheel_fp = cache_dir / self.wheel
        download_with_pip = not self.wheel_url or use_pip

        # Use local rehost to avoid downloading
        if use_local_rehost and g_backend_dirs.local_rehost:
            downloaded = self.download_from_local_rehost()

        # Even if cached, if using pip, redownload because we don't know
        # if the already downloaded file is valid
        if not downloaded:
            ilog.info(f"Download {wheel_fp} (use pip: {download_with_pip})")
            if download_with_pip:
                downloaded = self._download_wheel_with_pip(force=force)

            else:
                downloaded = self._download_wheel_with_requests(
                    force=force, stall_timeout=stall_timeout
                )

        self.downloaded = downloaded
        return downloaded


    def _install_dev(self) -> bool:
        installed: bool = False

        dev_dir = get_local_dev_dir() / self.name
        ilog.info(f"{self.name} install for dev: {str(dev_dir)}")
        if dev_dir.is_dir():
            cmd = f"{str(g_backend_dirs.python_exe)} -m pip install -e {str(dev_dir)}"
            env = generate_backend_env(exclude_append=['proxy',])
            try:
                result = subprocess.run(
                    cmd.split(),
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                # Check if 'Successfully installed' is in the output
                if "Successfully installed" in result.stdout.splitlines()[-1]:
                    ilog.info(f"{self.name} successfully installed for dev.")
                    installed = True

                else:
                    ilog.critical(f"{self.name} installation failed: {result.stdout}")

            except subprocess.CalledProcessError as e:
                ilog.critical(f"{self.name} failed to install package for dev: {e.stderr}")

            except Exception as e:
                ilog.critical(f"{self.name} installation encountered an error: {str(e)}")

        else:
            ilog.critical(f"{self.name} not a valid dir: {str(dev_dir)}")
            installed = True

        return installed


    def install(self, reinstall: bool = False, recover: bool = False) -> bool:
        version = self.version if self.version else self.latest_version
        ilog.info(f"Installing {self.name}=={version}")

        if self.version == 'dev':
            if not self.installed:
                self.installed = self._install_dev()
            self.send_end_progress(status='success' if self.installed else 'failed')
            return self.installed

        if self.uninstall_before:
            self.uninstall()

        cache_dir: Path = g_backend_dirs.cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        pnv = "==".join((self.name, self.version)) if self.version else self.name

        python_exe = str(g_backend_dirs.python_exe)
        cmd = f"{python_exe} -m pip install"
        if self.do_cache:
            cmd = f"{cmd} --find-links {cache_dir}"

        cmd = f"{cmd} {pnv}"

        if self.index_url:
            cmd = f"{cmd} --index-url={self.index_url}"
        if self.extra_index_url:
            cmd = f"{cmd} --extra_index_url-url={self.extra_index_url}"
        if reinstall:
            cmd = f"{cmd} --force-reinstall"
        if recover:
            cmd = f"{cmd} --force-reinstall --ignore-installed"

        ilog.debug(cmd)

        env = None
        ilog_print = ilog.info
        if g_backend_dirs.python_exe != sys.executable:
            env = generate_backend_env(exclude_append=['proxy',])
            ilog_print = ilog.debug

        try:
            process: subprocess.Popen = subprocess.Popen(
                cmd.split(),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )

            stdout: io.TextIOWrapper = process.stdout
            last_line: str = ""
            for line in stdout:
                ilog.info(f"pip: {line.rstrip()}")
                last_line = line
            process.communicate(timeout=10)

            if (
                "Successfully installed" in last_line
                or "Requirement already satisfied"  in last_line
            ):
                ilog_print(f"[{self.name}] Successfully installed")
                return True

            else:
                ilog.critical(f"Failed to install {self.name}")

        except subprocess.CalledProcessError as e:
            ilog.critical(f"Error installing {self.name}: {e.stderr}")

        except Exception as e:
            ilog.critical(f"Error installing {self.name}: {str(e)}")

        return False
