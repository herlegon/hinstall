import argparse
import os
import subprocess
import sys
import shutil
from pathlib import Path
import tarfile



def run_command(command, check=True):
    """Run a shell command and print its output."""
    print(f"[*] Running command: {command}")
    result = subprocess.run(command, shell=True, check=check, text=True)
    if result.returncode != 0:
        print(f"!!! ERROR: Command failed: {command}")
        sys.exit(-1)



def create_tar_gz_archive(src_dir, tar_gz_file):
    """Create a tar.gz file from the source directory."""
    print(f"[*] Creating tar.gz archive: {tar_gz_file}")
    with tarfile.open(tar_gz_file, 'w:gz') as tarf:
        # Add files to the tar.gz archive
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                file_path = Path(root) / file
                # Store relative paths in the archive
                arcname = file_path.relative_to(src_dir)
                tarf.add(file_path, arcname=arcname)



def main():

    PY_VERSION = "3.12.12"
    PY_DATE = "20251031"
    src_archive = f"cpython-{PY_VERSION}+{PY_DATE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
    release_archive = f"python-{PY_VERSION}-linux-x86_64.tar.gz"
    req_packages = [
        "requests",
        "websockets",
        ("hytils", 'local'),
        "setuptools",
    ]

    local_rehost_dir = (Path("/opt") / "herlegon" / "rehost").resolve()

    # Directories and filepaths
    src_fp = local_rehost_dir / "src" / src_archive
    workdir = local_rehost_dir / "work" / f"python-{PY_VERSION}-linux-x86_64-work"
    release_fp = local_rehost_dir / release_archive
    python_version: str = '.'.join(PY_VERSION.split('.')[:-1])


    # Verify that source is available
    if not src_fp.is_file():
        print(f"!!! ERROR: Archive not found at {src_fp}")
        sys.exit(1)


    # Do not regenerate new release if already exists
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Force rebuild even if release archive already exists"
    )
    args = parser.parse_args()
    if release_fp.exists() and not args.force:
        print(f"[✓] Release archive already exists at {release_fp}")
        print("[*] Use --force to rebuild.")
        return


    # Clean previous work directory
    print("[*] Cleaning old workdir...")
    if workdir.exists():
        shutil.rmtree(workdir)


    workdir.mkdir(parents=True)
    print(f"[*] Using local standalone Python archive: {src_fp}")

    print("[*] Extracting embedded Python...")
    run_command(f"tar -xzf {src_fp} -C {workdir} --strip-components=1")

    os.chdir(workdir)
    embed_python_exe = workdir / "bin" / f"python{python_version}"

    print("[*] Bootstrapping pip (ensurepip)...")
    run_command(f"{embed_python_exe} -m ensurepip --upgrade")

    print("[*] Upgrading packaging tools...")
    run_command(f"{embed_python_exe} -m pip install --no-cache-dir --upgrade pip setuptools wheel")

    # Install required python packages
    install_targets = []
    for pkg in req_packages:
        if isinstance(pkg, tuple | list) and pkg[1] == 'local':
            base: Path = (Path(__file__).parent.parent.parent / pkg[0] ).resolve()
            dist_dir = base / "dist"
            if dist_dir.exists() and dist_dir.is_dir():
                wheels = list(dist_dir.glob("*.whl"))
                if not wheels:
                    raise FileNotFoundError(f"No wheel found in: {dist_dir}")
                wheel = max(wheels, key=lambda p: p.stat().st_mtime)
                pkg = str(wheel.resolve())
        install_targets.append(pkg)
    print(f"[*] Installing requested packages: {', '.join(install_targets)}")
    run_command(f"{embed_python_exe} -m pip install --no-cache-dir {' '.join(install_targets)}")

    print("[*] Precompiling stdlib and site-packages...")
    run_command(f"{embed_python_exe} -m compileall -q -f lib/python{python_version} || true")
    run_command(f"{embed_python_exe} -m compileall -q -f lib64/python{python_version} || true")

    # Get the site-packages directory dynamically
    site_pkg_dir = subprocess.run(
        [embed_python_exe, "-c", "import site; print(site.getsitepackages()[0])"],
        check=True, capture_output=True, text=True
    ).stdout.strip()

    run_command(f"{embed_python_exe} -m compileall -q -f {site_pkg_dir} || true")

    print("[*] Cleaning unnecessary files...")
    python_lib: Path = workdir / 'lib' / f"python{python_version}"
    unnecessary_dirs = [
        python_lib / 'test',
        python_lib / 'ensurepip',
        python_lib / 'idlelib',
        python_lib / 'tkinter'
    ]

    # Remove unnecessary directories
    for dir in unnecessary_dirs:
        if dir.exists():
            shutil.rmtree(dir)

    # Clean empty __pycache__ directories
    for pycache in workdir.rglob('__pycache__'):
        if not any(pycache.iterdir()):
            pycache.rmdir()

    # Switch to the final destination path to create the tar.gz file
    os.chdir(local_rehost_dir)
    create_tar_gz_archive(workdir, release_fp)

    if workdir.exists():
        shutil.rmtree(workdir)
    print(f"[✓] Build complete: {release_fp}")


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()
