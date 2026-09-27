from pathlib import Path
import platform
from pprint import pprint
import sys

from hytils import lightgreen, red, yellow
sys.path.append(str(Path(__file__).resolve().parent.parent))
from hinstall import ilog


import sys
import platform
import re

def get_python_tags():
    """
    Returns Python tags in priority order.
    Example:
        [('cp314', 'cp314'),
         ('cp312', 'cp312'),
         ('cp311', 'abi3'),
         ('cp310', 'abi3'),
         ('py312', 'none'),
         ('py3', 'none'),
         ('py2.py3', 'none')]
    """
    py = sys.version_info
    tags = []

    # 1. Exact match: CPython-only
    cp = f"cp{py.major}{py.minor}"
    tags.append((cp, cp))

    # 2. abi3 compatibility (stable ABI)
    for minor in range(6, py.minor + 1):
        tags.append((f"cp3{minor}", "abi3"))

    # 3. Universal Python tags
    tags.append((f"py{py.major}{py.minor}", "none"))
    tags.append((f"py{py.major}", "none"))
    tags.append(("py3", "none"))
    tags.append(("py2.py3", "none"))

    return tags



def get_platform_tags():
    """
    Returns platform tags in priority order.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    tags = []

    if system == "windows":
        if machine in ("amd64", "x86_64"):
            tags.append("win_amd64")
        elif machine in ("x86", "i386", "i686"):
            tags.append("win32")
        elif machine == "arm64":
            tags.append("win_arm64")

    elif system == "darwin":
        # macOS
        ver = platform.mac_ver()[0]
        major, minor, *_ = (ver.split(".") + ["0", "0"])[:2]
        major, minor = int(major), int(minor)

        if machine == "arm64":
            for v in range(max(major, 11), 10, -1):
                tags.append(f"macosx_{v}_0_arm64")
        else:
            for v in range(major, 9, -1):
                if v >= 11:
                    tags.append(f"macosx_{v}_0_x86_64")
                else:
                    for mn in range(15, -1, -1):
                        tags.append(f"macosx_{v}_{mn}_x86_64")

    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            arch = "x86_64"
        elif machine in ("aarch64", "arm64"):
            arch = "aarch64"
        elif machine in ("i386", "i686"):
            arch = "i686"
        else:
            arch = machine

        tags += [
            f"manylinux_2_28_{arch}",
            f"manylinux_2_17_{arch}",
            f"manylinux2014_{arch}",
            f"manylinux_2_12_{arch}",
            f"manylinux2010_{arch}",
            f"manylinux_2_5_{arch}",
            f"manylinux1_{arch}",
            f"linux_{arch}",
        ]

    return tags
def parse_wheel_filename(filename):
    """
    Parse wheel filename into components.
    Returns:
        {
            name,
            version,
            python,
            abi,
            platforms: [list],
            filename
        }
    """
    if not filename.endswith(".whl"):
        return None

    stem = filename[:-4]
    parts = stem.split("-")

    if len(parts) < 5:
        return None

    python = parts[-3]
    abi = parts[-2]
    platforms = parts[-1].split(".")

    # everything before python/abi/platform is name-version-build
    name_version_parts = parts[:-3]

    # find where version starts
    ver_index = None
    for i, p in enumerate(name_version_parts):
        if p and p[0].isdigit():
            ver_index = i
            break

    if ver_index is None:
        return None

    name = "-".join(name_version_parts[:ver_index])
    version = "-".join(name_version_parts[ver_index:])

    return {
        "name": name,
        "version": version,
        "python": python,
        "abi": abi,
        "platforms": platforms,
        "filename": filename,
    }



def wheel_matches_python(wheel, python_tags):
    py = wheel["python"]
    abi = wheel["abi"]

    for py_tag, abi_tag in python_tags:

        # exact match: required for native wheels
        if py == py_tag and abi == abi_tag:
            return True

        # universal wheels (py3-none-any, py2.py3-none-any)
        if abi == "none" and py in {py_tag, "py3", "py2.py3"}:
            return True

    return False



def wheel_matches_platform(wheel, platform_tags):
    plats = wheel["platforms"]

    # universal wheels
    if plats == ["any"]:
        return True

    return any(pt in plats for pt in platform_tags)
















def filter_compatible_wheels(releases_data, version):
    """
    Filter wheel files from PyPI releases data to find compatible ones.

    Args:
        releases_data: dict like {'releases': {'1.0.0': [{'filename': '...', ...}]}}
        version: version string like '1.0.0'

    Returns:
        List of file dicts, sorted by compatibility (best first)
    """
    python_tags = get_python_tags()
    platform_tags = get_platform_tags()
    # ilog.debug(f"python_tags")
    # pprint(python_tags)
    # ilog.debug(f"platform_tags")
    # pprint(platform_tags)

    candidates = []

    for file_info in releases_data['releases'][version]:
        filename = file_info['filename']
        print(filename)

        # Skip non-wheel files
        if not filename.endswith('.whl'):
            continue

        # Parse the wheel filename
        wheel = parse_wheel_filename(filename)
        if not wheel:
            continue
        pprint(wheel)

        if not wheel_matches_python(wheel, python_tags):
            continue

        if not wheel_matches_platform(wheel, platform_tags):
            continue


        # compute priority
        prio = 0

        # python priority
        for i, (py_tag, abi_tag) in enumerate(python_tags):
            if wheel["python"] == py_tag or wheel["python"] in ("py3", "py2.py3"):
                prio += i * 10
                break

        # platform priority
        for i, plat in enumerate(platform_tags):
            if plat in wheel["platforms"] or wheel["platforms"] == ["any"]:
                prio += i
                break

        candidates.append((prio, file_info))

    # Sort by priority and return file info only
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]


# Example usage with your code pattern:
def example_usage():
    """Example showing how to use with PyPI data"""

    # Simulated PyPI data structure
    data = {
        'releases': {
            '80.9.0': [
                {'filename': "setuptools-80.9.0-py3-none-any.whl", 'url': "ftgyhuj"},
                {'filename': "setuptools-80.9.0.tar.gz}", 'url': "ftgyhuj"},
                # {'filename': 'psutil-7.1.3-cp37-abi3-win_amd64.whl', 'url': '...'},
                # {'filename': 'psutil-7.1.3-cp36-abi3-manylinux2010_x86_64.manylinux_2_12_x86_64.whl', 'url': '...'},
                # {'filename': 'psutil-7.1.3.tar.gz', 'url': '...'},
            ]
        }
    }

    version = '80.9.0'

    # New way (handles multiple tags correctly)
    files = filter_compatible_wheels(data, version)

    if files:
        print(f"Best match: {files[0]['filename']}")
    else:
        print("No compatible wheel found")

    return files



def main():
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"System: {platform.system()} {platform.machine()}")

    print(f"\nCompatible tags (in priority order):")
    print("\nPython tags:")
    for i, (py, abi) in enumerate(get_python_tags()[:5], 1):
        print(f"  {i}. {py}-{abi}")

    print(f"\nPlatform tags:")
    for i, tag in enumerate(get_platform_tags()[:10], 1):
        print(f"  {i}. {tag}")


    example_usage()


if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
Find which wheel file matches your platform - pure stdlib only.
Handles multiple platform tags in wheel filenames correctly.
"""


