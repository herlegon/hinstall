import os
from pathlib import Path
from tarfile import TarFile
import time
from zipfile import ZipFile
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

from .logger import ilog
from .api import InstallProgress



PLATFORMS: tuple[str] = ('win32', 'linux', 'darwin')


def get_domain_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    # Extract the netloc (domain) part and remove the "www." prefix if present
    domain = parsed_url.netloc
    if domain.startswith("www."):
        domain = domain[4:]  # Remove the "www." prefix
    return domain



def check_site_reachable(url: str, max_retries: int = 3):
    """Check if site is reachable with retries"""
    for attempt in range(max_retries):
        try:
            # Ensure the URL includes the scheme (https://)
            if not url.startswith('http'):
                url = 'https://' + url

            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            urlopen(req, timeout=1)
            return True

        except (URLError, HTTPError) as e:
            ilog.debug(f"{url} is not reachable, retry {attempt} - {e}")
            if attempt < max_retries - 1:
                continue
    ilog.status(f"[ce] Site is not reachable: {get_domain_from_url(url)}")
    return False



class ProgressWrapper:
    def __init__(
        self,
        raw_response,
        total_size: int,
        update_threshold=512*1024,
    ):
        self.raw = raw_response
        self.update_threshold = update_threshold
        self.bytes_downloaded = 0
        self.total_size = total_size
        self.last_time = time.time()


    def read(self, size=-1):
        data = self.raw.read(size)
        if data:
            self.bytes_downloaded += len(data)
            if self.bytes_downloaded >= self.update_threshold:
                if time.time() - self.last_time >= 0.25:
                    ilog.info(f"[pg]{min(100. * self.bytes_downloaded/self.total_size, 100):.1f}")
                self.bytes_downloaded = 0
            self.last_time = time.time()
        return data


    def flush_progress(self):
        """Call this after download completes to update remaining bytes"""
        if self.bytes_downloaded > 0:
            self.bytes_downloaded = 0



def extract_zip_file(
    pkg_name: str,
    compressed_data: ZipFile,
    install_dir: Path,
    exclude: list[str] = [],
    task_name: str = "",
) -> None:
    """Extract ZIP archive with progress tracking, excluding specified names"""
    ilog.status(f"[si]{pkg_name}")

    def should_exclude(path: Path) -> bool:
        """Check if any part of the path matches excluded names"""
        return any(part in exclude for part in path.parts) or path.name in exclude

    all_files = [f for f in compressed_data.namelist() if not f.endswith('/')]
    total_files = len(all_files)

    # Check for single root folder
    root_folders = set()
    for file in all_files:
        parts = Path(file).parts
        if parts:
            root_folders.add(parts[0])

    has_single_root = len(root_folders) == 1
    root_folder = root_folders.pop() if has_single_root else None

    ilog.progress(
        InstallProgress(
            package_name=pkg_name,
            status='installing',
            type='progress',
            progress=0.0,
            total=total_files,
            completed=0,
            unit='files',
            description=f"Extracting {pkg_name}",
        )
    )

    extracted_count = 0
    last_time = time.time()
    # Extract files
    for file in all_files:
        file_path = Path(file)

        # Handle single root folder
        if has_single_root and root_folder is not None:
            if file == root_folder or file == f'{root_folder}/':
                continue
            file_path = file_path.relative_to(root_folder)

        if not should_exclude(file_path):
            target_path = install_dir / file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with compressed_data.open(file) as source:
                target_path.write_bytes(source.read())

        extracted_count += 1
        current_time = time.time()
        if current_time - last_time >= 0.1 or extracted_count == total_files:
            pct = min(100.0 * extracted_count / total_files, 100.0) if total_files else 100.0
            ilog.status(f"[pg]{pct:.1f}")
            ilog.progress(
                InstallProgress(
                    package_name=pkg_name,
                    status='installing',
                    type='progress',
                    progress=pct,
                    total=total_files,
                    completed=extracted_count,
                    unit='files',
                    description=f"Extracting {pkg_name}",
                )
            )
            last_time = current_time

    ilog.status(f"[ei]{pkg_name}")



def extract_tar_file(
    pkg_name,
    compressed_data: TarFile,
    install_dir: Path,
    exclude: list[str] = None,
) -> None:
    start_time = time.time()
    if True:
        _extract_tar_file_file_count(
            pkg_name,
            compressed_data,
            install_dir,
            exclude,
        )
    else:
        _extract_tar_file_file_size(
            pkg_name,
            compressed_data,
            install_dir,
            exclude,
        )
    ilog.debug(f"elapsed: {time.time() - start_time:.2f}s")


def _extract_tar_file_file_size(
    pkg_name: str,
    compressed_data: TarFile,
    install_dir: Path,
    exclude: list[str] = None,
) -> None:
    """Extract TAR archive with progress tracking (based on file sizes),
       excluding specified names, without double extraction.
    """
    ilog.status(f"[si]{pkg_name}")

    if exclude is None:
        exclude = []

    def should_exclude(path: Path) -> bool:
        """Check if any part of the path matches excluded names"""
        return any(part in exclude for part in path.parts) or path.name in exclude

    # ---------- FAST PRE-SCAN (NO EXTRACTION) ----------
    members = compressed_data.getmembers()

    # Count only files for size (symlinks have no data)
    total_bytes = sum(m.size for m in members if m.isfile())

    # Detect single root folder
    root_folders = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
    has_single_root = len(root_folders) == 1
    root_folder = next(iter(root_folders)) if has_single_root else None

    # ---------- EXTRACTION ----------
    extracted_bytes = 0

    for member in members:
        file_path = Path(member.name)

        # strip root folder
        if has_single_root and root_folder:
            if file_path.parts and file_path.parts[0] == root_folder:
                file_path = file_path.relative_to(root_folder)

        # Skip excluded paths
        if not should_exclude(file_path):
            # ilog.info(f"{task_name}:progress={member.size}")
            continue

        target_path = install_dir / file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Regular file
        if member.isfile():
            source = compressed_data.extractfile(member)
            if source:
                target_path.write_bytes(source.read())
            os.chmod(target_path, member.mode)

        # Symbolic link
        elif member.issym():
            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()
            target_path.symlink_to(member.linkname)

        # Hard link
        elif member.islnk():
            link_target = Path(member.linkname)
            if has_single_root and root_folder and link_target.parts[0] == root_folder:
                link_target = link_target.relative_to(root_folder)
            target_path.hardlink_to(install_dir / link_target)

        # Progress update (only for actual file data)
        ilog.status(f"[pg]{min(100. * extracted_bytes/total_bytes, 100):.1f}")
        extracted_bytes += member.size

    ilog.status(f"[ei]{pkg_name}")



def _extract_tar_file_file_count(
    pkg_name: str,
    compressed_data: TarFile,
    install_dir: Path,
    exclude: list[str] = [],
) -> None:
    """Extract TAR archive with progress tracking, excluding specified names"""
    ilog.status(f"[si]{pkg_name}")

    def should_exclude(path: Path) -> bool:
        """Check if any part of the path matches excluded names"""
        return any(part in exclude for part in path.parts) or path.name in exclude

    members = compressed_data.getmembers()
    file_members = [m for m in members
                    if m.isfile() or m.issym() or m.islnk()]
    total_files = len(file_members)

    # detect single root folder
    root_folders = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
    has_single_root = len(root_folders) == 1
    root_folder = next(iter(root_folders)) if has_single_root else None

    ilog.info(f"Extract {total_files} files")
    ilog.progress(
        InstallProgress(
            package_name=pkg_name,
            status='installing',
            type='progress',
            progress=0.0,
            total=total_files,
            completed=0,
            unit='files',
            description=f"Extracting {pkg_name}",
        )
    )

    # Extract files
    extracted_count = 0
    last_time = time.time()
    for member in file_members:
        file_path = Path(member.name)

        # handle single root folder
        if has_single_root and root_folder:
            if file_path.parts and file_path.parts[0] == root_folder:
                file_path = file_path.relative_to(root_folder)

        # skip excluded
        # if should_exclude(file_path):
        #     ilog.info(f"{task_name}progress={extracted_count}")

        if not should_exclude(file_path):
            target_path = install_dir / file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # regular file
            if member.isfile():
                source = compressed_data.extractfile(member)
                if source:
                    target_path.write_bytes(source.read())
                os.chmod(target_path, member.mode)

            # symbolic link
            elif member.issym():
                if target_path.exists() or target_path.is_symlink():
                    target_path.unlink()
                target_path.symlink_to(member.linkname)

            # hard link
            elif member.islnk():
                link_target = Path(member.linkname)
                if has_single_root and root_folder and link_target.parts and link_target.parts[0] == root_folder:
                    link_target = link_target.relative_to(root_folder)
                target_path.hardlink_to(install_dir / link_target)

        extracted_count += 1
        current_time = time.time()
        # update progress
        if current_time - last_time >= 0.1 or extracted_count == total_files:
            pct = min(100.0 * extracted_count / total_files, 100.0) if total_files else 100.0
            ilog.status(f"[pg]{pct:.1f}")
            ilog.progress(
                InstallProgress(
                    package_name=pkg_name,
                    status='installing',
                    type='progress',
                    progress=pct,
                    total=total_files,
                    completed=extracted_count,
                    unit='files',
                    description=f"Extracting {pkg_name}",
                )
            )
            last_time = current_time

    ilog.status(f"[ei]{pkg_name}")

