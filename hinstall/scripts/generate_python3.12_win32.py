import argparse
from datetime import datetime
import os
import sys
import shutil
import zipfile
import subprocess
import compileall
import urllib.request
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
    PY_VERSION = "3.12.10"
    src_archive: str = f"python-{PY_VERSION}-embed-amd64.zip"
    timestamp: str = datetime.now().strftime("%Y%m%dT%Hh%M")
    release_archive = f"python-{PY_VERSION}-win-x86_64-{timestamp}.tar.gz"
    req_packages = [
        "requests",
        "websockets",
        "setuptools",
        # "wheel",
        # ("hytils", 'local'),
        "hytils",
    ]

    local_rehost_dir = (Path(__file__).parent.parent.parent / "herlegon" / "rehost").resolve()

    # Directories and filepaths
    src_fp = local_rehost_dir / "src" / src_archive
    workdir = local_rehost_dir / "work" / f"python-{PY_VERSION}-win-x86_64-work"
    release_fp = local_rehost_dir / release_archive


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


    # Extract
    print("[*] Extracting embedded Python...")
    with zipfile.ZipFile(src_fp, "r") as zf:
        zf.extractall(workdir)


    # Enable import site
    pth_files = list(workdir.glob("*.pth")) + list(workdir.glob("*._pth"))
    if not pth_files:
        raise RuntimeError("No _pth file found.")
    pth_file = pth_files[0]
    print(f"[*] Found path config: {pth_file.name}")
    text = pth_file.read_text(encoding="utf-8")
    if "import site" not in text:
        text += ("\n" if not text.endswith("\n") else "") + "import site\n"
        pth_file.write_text(text, encoding="utf-8")
        print("    -> Added 'import site' to path file.")
    else:
        print("    -> 'import site' already present.")


    # Prepare minimal Lib structure
    lib_dir = workdir / "Lib"
    lib_dir.mkdir(exist_ok=True)
    (lib_dir / "site-packages").mkdir(parents=True, exist_ok=True)


    # Download latest get-pip script
    get_pip = workdir / "get-pip.py"
    if not get_pip.exists():
        print("[*] Downloading get-pip.py...")
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
    else:
        print("[*] Using existing get-pip.py")


    # Bootstrap pip with proper env
    python_version: str = ''.join(PY_VERSION.split('.')[:-1])
    print("[*] Installing pip into embedded runtime...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workdir / f"python{python_version}.zip") + os.pathsep + str(lib_dir)

    result = subprocess.run(
        [str(workdir / "python.exe"), str(get_pip.resolve()), "--no-warn-script-location"],
        cwd=workdir,
        env=env,
    )
    if result.returncode != 0:
        print("!!! pip bootstrap failed.")
        sys.exit(result.returncode)


    # After pip installation, create wrapper batch files
    scripts_dir = workdir / "Scripts"
    if not scripts_dir.exists():
        scripts_dir.mkdir()

    # Create pip.bat wrapper
    pip_bat = scripts_dir / "pip.bat"
    pip_bat.write_text(
        '@echo off\n'
        '"%~dp0..\\python.exe" -m pip %*\n'
    )

    # Create pip3.bat wrapper
    pip3_bat = scripts_dir / "pip3.bat"
    pip3_bat.write_text(
        '@echo off\n'
        '"%~dp0..\\python.exe" -m pip %*\n'
    )

    # Remove the problematic .exe launchers
    for exe in scripts_dir.glob("pip*.exe"):
        exe.unlink()


    # Ensure site-packages visible
    print("[*] Ensuring site-packages path in ._pth file...")
    pth_file = next(workdir.glob(f"python{python_version}._pth"))
    lines = [ln.strip() for ln in pth_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if "Lib" not in lines:
        lines.insert(0, "Lib")
    if "Lib\\site-packages" not in lines and "Lib/site-packages" not in lines:
        lines.insert(1, "Lib\\site-packages")
    if "import site" not in lines:
        lines.append("import site")
    pth_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


    # Verify pip
    print("[*] Checking pip version...")
    subprocess.run([str(workdir / "python.exe"), "-m", "pip", "--version"], cwd=workdir)


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
    subprocess.run(
        [str(workdir / "python.exe"), "-m", "pip", "install", "--no-cache-dir", *install_targets],
        cwd=workdir,
        check=True,
    )


    # Precompile
    print("[*] Precompiling all .py files to .pyc...")
    compileall.compile_dir(lib_dir, force=True, quiet=1)

    zip_stdlib = workdir / f"python{python_version}.zip"
    if zip_stdlib.exists():
        print("[*] Extracting and precompiling stdlib...")
        stdlib_extract = workdir / "_stdlib"
        with zipfile.ZipFile(zip_stdlib, "r") as zf:
            zf.extractall(stdlib_extract)
        compileall.compile_dir(stdlib_extract, force=True, quiet=1)

        print(f"    -> Repacking python{python_version}.zip with .pyc only...")
        with zipfile.ZipFile(zip_stdlib, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for pyc in stdlib_extract.rglob("*.pyc"):
                zf.write(pyc, pyc.relative_to(stdlib_extract))
        shutil.rmtree(stdlib_extract)


    # Remove unnecessary files
    print("[*] Cleaning unnecessary files...")
    for pattern in (
        # "*.txt",  <- no because licenses
        "*.cat",
        "get-pip.py"
    ):
        for f in workdir.glob(pattern):
            f.unlink(missing_ok=True)


    # Switch to the final destination path to create the zip file
    os.chdir(local_rehost_dir)
    create_tar_gz_archive(workdir, release_fp)

    if workdir.exists():
        shutil.rmtree(workdir)
    print(f"[✓] Build complete: {release_fp}")



if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()

