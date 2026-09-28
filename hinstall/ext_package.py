
from dataclasses import dataclass
import tempfile
from hytils import get_extension
from pathlib import Path
import re
import shutil
import requests
import time

from .backend_dirs import g_backend_dirs
from .utils import (
    ProgressWrapper,
    check_site_reachable,
    extract_tar_file,
    extract_zip_file,
    get_domain_from_url,
)
from .logger import ilog
from .api import InstallProgress




@dataclass
class ExtPackage:
    name: str
    filename: str
    key: str
    variant: str = ""

    # Installation, skip is not necessary except for dev and to keep the
    # definitions in the config file
    skip: bool = False
    install_dir: Path = None
    installed: bool = False

    # Where to download from
    tag: str = ""
    size: int = 0
    host: str = ''

    # to remove after validation
    response: requests.Response | None = None

    # Downloaded/cached
    downloaded: bool = False
    cache_file: Path = None
    do_cache: bool = False

    _use_local_rehost: bool = False
    _retry_count: int = 3

    def __post_init__(self):
        self.skip = bool(self.filename == '')
        if self.do_cache:
            self.cache_file = g_backend_dirs.cache / self.filename
        else:
            self.cache_file = Path(tempfile.gettempdir()) / "herlegon" / self.filename

    @property
    def retry_count(self) -> int:
        return self._retry_count


    @retry_count.setter
    def retry_count(self, count: int) -> None:
        self._retry_count = count


    @property
    def use_local_rehost(self) -> bool:
        return self._use_local_rehost


    @use_local_rehost.setter
    def use_local_rehost(self, enable: bool) -> None:
        self._use_local_rehost = enable


    def _update_cache_file(self) -> Path:
        if self.do_cache:
            self.cache_file = g_backend_dirs.cache / self.filename
        else:
            self.cache_file = Path(tempfile.gettempdir()) / "herlegon" / self.filename
        return self.cache_file


    def update_tag(self) -> None:
        ilog.debug(f"update_tag for {self.name}")

        fp: Path = Path(self.filename)
        self.tag = (
            Path(fp.stem).stem
            if fp.suffix in (".gz", ".bz", ".xz")
            and fp.stem.endswith(".tar")
            else fp.stem
        )


    def is_up_to_date(self) -> bool | None:
        if not self.install_dir.is_dir():
            ilog.debug(f"{self.install_dir} doesn't exist")
            self.installed = False
            return False

        # Must be installed and tag must match
        if self.tag:
            tag_fp: Path = self.install_dir / self.tag
            if tag_fp.exists():
                self.installed = True
                ilog.info(f"{self.name}: already installed and up-to-date")
                return True

        return None


    def is_installed(self, up_to_date: bool = True) -> bool | None:
        if up_to_date:
            return self.is_up_to_date()

        if not self.install_dir.is_dir():
            self.installed = False
            return False

        # Iterate over files in the directory
        filename_pattern = re.compile(
            rf"^{self.filename}(_\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}})"
        )
        tag_exists: bool = False
        for file in self.install_dir.iterdir():
            if (
                file.is_file()
                and file.stat().st_size == 0
                and filename_pattern.match(file.name)
            ):
                tag_exists = True
                break

        if not tag_exists:
            self.installed = False
            return False

        # At least a tag but not sure it's up-to-date
        return tag_exists


    def is_cached(self) -> bool:
        self._update_cache_file()
        ilog.debug(f"Searching cache file: {self.cache_file}")
        tag_fp: Path = g_backend_dirs.cache / self.tag
        if (
            self.tag and tag_fp.exists()
            and self.cache_file.is_file()
            and self.cache_file.stat().st_size == self.size
        ):
            self.downloaded = True
            ilog.debug(f"{self.name} installer cached")
            return True
        else:
            ilog.debug(f"{self.name} installer is not cached yet")

        return False



    def clean_cache(self) -> None:
        # clean cache of other version
        self._update_cache_file()
        ilog.debug(f"Clean cache")
        if self.cache_file is None:
            return
        for file in self.cache_file.parent.iterdir():
            if (
                file.is_file()
                and file.name.startswith(self.key)
                and file.name not in (
                    self.tag,
                    self.filename
                )
            ):
                file.unlink()

        if not self.do_cache:
            ilog.debug(f"Remove cached installed files")
            for file in self.cache_file.parent.iterdir():
                if file.is_file() and file.name.startswith(self.key):
                    file.unlink()



    def download_from_local_rehost(self) -> bool:
        if g_backend_dirs.local_rehost is None:
            raise ValueError(f"local_rehost must be defined")

        local_fp: Path = g_backend_dirs.local_rehost / self.filename
        ilog.debug(f"[{self.name}] download from local host: {local_fp}")
        ilog.status(f"[sd]{self.name}")

        if local_fp.exists():
            self._update_cache_file()
            cache_dir = self.cache_file.parent
            cache_dir.mkdir(parents=True, exist_ok=True)
            file_size = local_fp.stat().st_size
            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='downloading',
                    type='progress',
                    progress=0.0,
                    total=file_size,
                    completed=0,
                    unit='B',
                    description=f"Copying {self.name}",
                )
            )

            with open(local_fp, 'rb') as src, open(self.cache_file, 'wb') as dst:
                copied = 0
                last_time = time.time()
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    dst.write(buf)
                    copied += len(buf)
                    current_time = time.time()
                    if current_time - last_time >= 0.1 and file_size > 0:
                        pct = min(100.0 * copied / file_size, 100.0)
                        ilog.progress(
                            InstallProgress(
                                package_name=self.name,
                                status='downloading',
                                type='progress',
                                progress=pct,
                                total=file_size,
                                completed=copied,
                                unit='B',
                                description=f"Copying {self.name}",
                            )
                        )
                        last_time = current_time

            (cache_dir / self.tag).touch(exist_ok=True)
            ilog.debug(f"Copied to {cache_dir}")
            self.downloaded = True
            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='success',
                    type='progress',
                    progress=100.0,
                    total=file_size,
                    completed=file_size,
                    unit='B',
                    description=f"Copied {self.name}",
                )
            )

        else:
            ilog.error(f"File is missing: {local_fp}")
            self.downloaded = False
            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='failed',
                    type='progress',
                    progress=0.0,
                    description=f"Missing {self.name}",
                )
            )

        if self.downloaded:
            ilog.status(f"[ed]{self.name}")
        else:
            ilog.status(f"[fd]{self.name}")
        return self.downloaded



    def download_from_host(self) -> bool:
        if not self.tag:
            ilog.error(f"Tag file not valid for package: {self.name}")
            ilog.status(f"[ce]{self.name}: tag is not valid.")
            return False

        # Force to false because we clean the cache directories
        self.downloaded = False

        self._update_cache_file()
        tmp_dir = self.cache_file.parent
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tag_file = (tmp_dir / self.tag)
        if tag_file.exists():
            tag_file.unlink()

        ilog.debug(f"Download package: {self.filename} to {tmp_dir}")

        host = self.host[:-1] if self.host.endswith("/") else self.host
        url = f"{host}/{self.filename}"
        ilog.debug(f"url: {url}")

        _retry: int = self.retry_count
        while _retry:
            ilog.status(f"[sd]{self.name}")
            ilog.status(f"[pg]0.")

            try:
                response = requests.get(
                    url,
                    stream=True,
                    timeout=10,
                    allow_redirects=True
                )
                response.raise_for_status()

                content_len = response.headers.get('content-length')
                total_size = int(content_len) if content_len and content_len.isdigit() else self.size
                if self.size == 0 and total_size > 0:
                    self.size = total_size

                ilog.progress(
                    InstallProgress(
                        package_name=self.name,
                        status='downloading',
                        type='progress',
                        progress=0.0,
                        total=total_size,
                        completed=0,
                        unit='B',
                        description=f"Downloading {self.name}",
                    )
                )

                downloaded = 0
                last_time = time.time()
                with open(self.cache_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            current_time = time.time()
                            if current_time - last_time >= 0.1 and total_size > 0:
                                pct = min(100.0 * downloaded / total_size, 100.0)
                                ilog.progress(
                                    InstallProgress(
                                        package_name=self.name,
                                        status='downloading',
                                        type='progress',
                                        progress=pct,
                                        total=total_size,
                                        completed=downloaded,
                                        unit='B',
                                        description=f"Downloading",
                                    )
                                )
                                last_time = current_time

                tag_file.touch()
                self.downloaded = True
                ilog.status(f"[ed]{self.name}")
                ilog.progress(
                    InstallProgress(
                        package_name=self.name,
                        status='success',
                        type='progress',
                        progress=100.0,
                        total=total_size if total_size > 0 else downloaded,
                        completed=downloaded,
                        unit='B',
                        description=f"Downloaded",
                    )
                )
                return True

            except Exception as e:
                ilog.debug(f"[W] Retry to download. Reason: {type(e)} - {str(e)}")
                _retry -= 1
                if _retry == 0:
                    ilog.debug(f"[E] failed to download {self.filename}")
                    ilog.status(f"[df]{self.name}")
                    ilog.progress(
                        InstallProgress(
                            package_name=self.name,
                            status='failed',
                            type='progress',
                            progress=0.0,
                            description=f"Failed {self.name}",
                        )
                    )
                    return False




    def install(self) -> bool:
        installed: bool = False
        self.installed = False

        if not self.downloaded:
            ilog.error(f"Cannot install {self.name}. Reason: not downloaded")
            ilog.status(f"[if]{self.name}")
            return False

        install_dir = self.install_dir
        ilog.debug(f"Install: {self.name} in {install_dir}")

        self._update_cache_file()
        extension: str = get_extension(str(self.cache_file))
        if install_dir.exists():
            shutil.rmtree(install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)

        exclude: list[str] = []
        if self.key.lower() == 'ffmpeg':
            exclude = ('doc', 'man', 'ffplay')

        if (
            extension in ('.gz', '.xz')
            and str(self.cache_file).endswith(f'.tar{extension}')
        ):
            import tarfile

            compression = extension.lstrip('.')
            try:
                with tarfile.open(self.cache_file, f"r:{compression}") as tar_file:
                    extract_tar_file(
                        pkg_name=self.name,
                        compressed_data=tar_file,
                        install_dir=install_dir,
                        exclude=exclude,
                    )
                    installed = True
            except Exception as e:
                ilog.error(f"Failed to untar {self.cache_file}. Reason: {str(e)}")

        elif extension == '.zip':
            import zipfile

            try:
                with zipfile.ZipFile(self.cache_file, "r") as zip_file:
                    extract_zip_file(
                        pkg_name=self.name,
                        compressed_data=zip_file,
                        install_dir=install_dir,
                        exclude=exclude,
                    )
                    installed = True
            except Exception as e:
                ilog.error(f"Failed to unzip {self.cache_file}. Reason: {str(e)}")

        else:
            try:
                shutil.move(self.cache_file, install_dir)
                installed = True
            except Exception as e:
                ilog.error(f"Failed to copy {self.cache_file} to {install_dir}. Reason: {str(e)}")


        if installed:
            (install_dir / self.tag).touch()
            self.clean_cache()

            ilog.debug(f"{self.name} installed in {install_dir}")
            ilog.status(f"[ei]{self.name}")
            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='success',
                    type='progress',
                    progress=100.0,
                    description=f"Installed {self.name}",
                )
            )

        else:
            ilog.status(f"[if]{self.name}")
            ilog.progress(
                InstallProgress(
                    package_name=self.name,
                    status='failed',
                    type='progress',
                    progress=0.0,
                    description=f"Installation failed: {self.name}",
                )
            )

        self.installed = installed

        return installed

