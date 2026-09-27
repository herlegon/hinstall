#!/usr/bin/env python3
"""
Get wheel filename for your platform - pure stdlib, no dependencies.
Works on Windows, macOS, and Linux.
Handles abi3 (stable ABI) wheels correctly.
"""

import sys
import platform
import sysconfig

def get_platform_tag():
    """Generate platform tag using only stdlib."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in ("amd64", "x86_64"):
            plat = "win_amd64"
        elif machine in ("x86", "i386", "i686"):
            plat = "win32"
        elif machine == "arm64":
            plat = "win_arm64"
        else:
            plat = f"win_{machine}"

    elif system == "darwin":
        # macOS version
        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            parts = mac_ver.split('.')
            mac_ver_str = f"{parts[0]}_{parts[1] if len(parts) > 1 else '0'}"
        else:
            mac_ver_str = "10_9"  # fallback

        if machine == "arm64":
            plat = f"macosx_{mac_ver_str}_arm64"
        elif machine in ("x86_64", "amd64"):
            plat = f"macosx_{mac_ver_str}_x86_64"
        else:
            plat = f"macosx_{mac_ver_str}_{machine}"

    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            arch = "x86_64"
        elif machine in ("aarch64", "arm64"):
            arch = "aarch64"
        elif machine in ("i386", "i686"):
            arch = "i686"
        else:
            arch = machine

        plat = f"manylinux2014_{arch}"

    else:
        plat = sysconfig.get_platform().replace('-', '_').replace('.', '_')

    return plat

def get_compatible_tags():
    """
    Get list of compatible wheel tags in priority order.
    Returns list of (py_tag, abi_tag, platform_tag) tuples.
    """
    tags = []
    py_version = sys.version_info
    plat = get_platform_tag()

    # 1. Specific cpXY tag (e.g., cp312-cp312-win_amd64)
    py_tag = f"cp{py_version.major}{py_version.minor}"
    tags.append((py_tag, py_tag, plat))

    # 2. abi3 tags (stable ABI) - works from cp37 onwards for Python 3.12
    # Check backwards from cp37 to current version
    for minor in range(37, py_version.minor * 10 + py_version.major * 100 + 1):
        if minor < 37:
            continue
        abi3_tag = f"cp{minor // 10}{minor % 10}" if minor >= 30 else f"cp{minor}"
        tags.append((abi3_tag, "abi3", plat))

    # Simpler approach for abi3
    tags_abi3 = []
    for v in range(7, py_version.minor + 1):  # cp37 through current
        tags_abi3.append((f"cp3{v}", "abi3", plat))
    tags.extend(reversed(tags_abi3))  # Prefer newer abi3

    # 3. Pure Python wheels
    tags.append((f"py{py_version.major}{py_version.minor}", "none", "any"))
    tags.append((f"py{py_version.major}", "none", "any"))
    tags.append(("py3", "none", "any"))

    return tags

def format_wheel_name(package_name, version, py_tag, abi_tag, plat_tag):
    """Format complete wheel filename."""
    pkg = package_name.replace('-', '_')
    return f"{pkg}-{version}-{py_tag}-{abi_tag}-{plat_tag}.whl"

def find_matching_wheel(package_name, version="X.Y.Z"):
    """Show which wheels would match for this package."""
    tags = get_compatible_tags()

    print(f"Compatible wheels for {package_name} (in priority order):\n")

    for i, (py, abi, plat) in enumerate(tags[:15], 1):  # Show top 15
        wheel = format_wheel_name(package_name, version, py, abi, plat)
        print(f"{i}. {wheel}")

    print(f"\n... and more")

def show_info():
    """Display platform information."""
    py_version = sys.version_info
    plat = get_platform_tag()

    print(f"Python: {py_version.major}.{py_version.minor}.{py_version.micro}")
    print(f"System: {platform.system()}")
    print(f"Machine: {platform.machine()}")
    print(f"Platform tag: {plat}")
    print(f"\nMost specific wheel tag: cp{py_version.major}{py_version.minor}-cp{py_version.major}{py_version.minor}-{plat}")
    print(f"\nExample compatible wheels (in order of preference):")

    pkg = "psutil"
    ver = "7.1.3"

    print(f"\n1. {pkg}-{ver}-cp{py_version.major}{py_version.minor}-cp{py_version.major}{py_version.minor}-{plat}.whl")
    print(f"2. {pkg}-{ver}-cp37-abi3-{plat}.whl  ← abi3 (stable ABI)")
    print(f"3. {pkg}-{ver}-py3-none-any.whl  ← pure Python")





if __name__ == "__main__":
    # if len(sys.argv) > 1:
    #     package = sys.argv[1]
    #     version = sys.argv[2] if len(sys.argv) > 2 else "X.Y.Z"
    #     find_matching_wheel(package, version)
    # else:
    #     show_info()
    print(get_platform_tag())
