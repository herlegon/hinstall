
from pathlib import Path
import sys


def get_rehost_dir(company: str = "herlegon") -> Path:
    local_package_dir: Path

    if sys.platform == "win32":
        local_package_dir = Path("A:\\") / company / "rehost"

    elif sys.platform == "linux":
        local_package_dir = Path("/opt") / company / "rehost"

    elif sys.platform == "darwin":
        local_package_dir = Path.home() / company / "rehost"

    return local_package_dir

