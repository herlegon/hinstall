import time
from pathlib import Path
from typing import Callable, Iterable
from .api import InstallProgress
from .logger import ilog
import requests
import time
from pathlib import Path
from typing import Iterable

import requests
from .logger import ilog, RichProgressHandler
from .api import InstallProgress



def _emit(
    name: str,
    status: str = "",
    description: str = "",
    completed: int = 0,
    total: int = 0,
) -> None:
    ilog.progress(
        InstallProgress(
            package_name=name,
            status=status,
            type="progress",
            completed=completed,
            total=total,
            unit="B",
            description=description,
        )
    )



def _stop_rich_progress() -> None:
    """Ferme l'affichage Rich et réinitialise les tâches du handler."""
    for h in ilog.handlers:
        if isinstance(h, RichProgressHandler):
            h.stop()



def download_model(
    name: str,
    dest_dir: Path,
    base_url: str,
    force: bool = False,
    stall_timeout: float = 30,
    update_interval: float = 0.1,
) -> bool:
    url = f"{base_url.rstrip('/')}/{name}"
    dest_fp = dest_dir / name
    part_fp = dest_fp.with_name(dest_fp.name + ".part")
    dest_dir.mkdir(parents=True, exist_ok=True)

    started = False

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(10, stall_timeout),
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            if not force and dest_fp.is_file() and (
                total_size == 0 or dest_fp.stat().st_size == total_size
            ):
                # ilog.debug(f"Model already downloaded: {name}")
                return True

            if total_size == 0:
                ilog.warning(f"Unknown file size for {name}")

            # ilog.debug(f"Downloading {name} from {url}")
            desc = f"Downloading"
            _emit(name, description=desc, total=total_size)
            started = True

            downloaded = 0
            start_time = last_emit = time.time()

            with open(part_fp, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if total_size > 0 and now - last_emit >= update_interval:
                        _emit(
                            name,
                            description=desc,
                            completed=downloaded,
                            total=total_size,
                        )
                        last_emit = now

        if total_size and downloaded != total_size:
            raise IOError(f"Incomplete download: {downloaded}/{total_size} bytes")

        part_fp.replace(dest_fp)
        elapsed = time.time() - start_time
        # ilog.debug(f"Downloaded {name} ({downloaded / 1024**2:.1f} MB in {elapsed:.1f}s)")
        _emit(
            name,
            status="success",
            description=f"Downloaded ",
            completed=downloaded,
            total=total_size or downloaded,
        )
        return True

    except requests.exceptions.RequestException as e:
        ilog.error(f"Download failed for {name}: {e}")
    except Exception as e:
        ilog.critical(f"Unexpected error downloading {name}: {e}")

    part_fp.unlink(missing_ok=True)
    if started:
        _emit(name, status="failed", description=f"Download failed: {name}")
    return False



def download_models(
    names: Iterable[str],
    dest_dir: Path,
    base_url: str,
    force: bool = False
) -> dict[str, bool]:
    try:
        return {
            name: download_model(
                name=name,
                dest_dir=dest_dir,
                base_url=base_url,
                force=force,
            )
            for name in names
        }
    finally:
        _stop_rich_progress()
