from dataclasses import dataclass
import sys
import os
from pathlib import Path
from .logger import ilog

ORGANIZATION: str = "herlegon"

@dataclass(slots=True)
class BackendDirectories:
    app: Path
    python_exe: Path
    external: Path
    cache: Path
    models: Path
    local_rehost: Path = None



def get_backend_dirs(
    app_name: str = "hconvert",
    organization: str = ORGANIZATION
) -> BackendDirectories:
    """Get platform-specific backend directory"""

    if sys.platform == "win32":
        # Windows: Use AppData\Local
        base = Path(
            os.environ.get('LOCALAPPDATA', Path.home() / "AppData" / "Local")
        )
        cache_dir = base / organization / "cache"
        python_exe = "python.exe"

    elif sys.platform == "linux":
        # Linux: Use XDG Base Directory
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / ".local" / "share"))
        # Use this dir for dev because limited bandwidth to never delete it
        cache_dir = Path(f"/opt/{organization}/cache")
        python_exe = Path("bin") / "python"

    elif sys.platform == "darwin":
        # macOS: Use Application Support
        base = Path.home() / "Library" / "Application Support"
        cache_dir = base / organization / "cache"
        python_exe = "python"

    else:
        ilog.error(f"Unsupported platform: {sys.platform}")

    return BackendDirectories(
        app=base / organization / app_name,
        python_exe=base / organization / "python" / python_exe,
        external=base / organization,
        cache=cache_dir,
        models=base / organization / "models",
    )
g_backend_dirs: BackendDirectories = get_backend_dirs()



def get_local_dev_dir(organization: str = ORGANIZATION) -> Path:
    local_dev_dir: Path

    if sys.platform == "win32":
        local_dev_dir = Path("A:\\")

    elif sys.platform == "linux":
        local_dev_dir = Path.home() / "github"

    elif sys.platform == "darwin":
        local_dev_dir = Path.home() / organization

    return local_dev_dir
