import os
from pathlib import Path
from pprint import pprint
import sys
import subprocess

sys.path.append(str(Path(__file__).resolve().parent.parent))
from hinstall import (
    generate_backend_env,
    g_backend_env
)


if __name__ == "__main__":
    backend_env = generate_backend_env()


    # 1. Determine the shell and arguments
    if sys.platform == "win32":
        shell = "powershell.exe"
        clear_conda_ps = (
            "Remove-Item Env:CONDA_EXE -ErrorAction Ignore; "
            "Remove-Item Env:CONDA_EXES -ErrorAction Ignore; "
            "Remove-Item Env:CONDA_SHLVL -ErrorAction Ignore; "
            "Remove-Item Env:CONDA_PREFIX -ErrorAction Ignore; "
            "Remove-Item Env:CONDA_DEFAULT_ENV -ErrorAction Ignore; "
            "Remove-Item Env:CONDA_PROMPT_MODIFIER -ErrorAction Ignore; "
            "Remove-Item Env:_CE_CONDA -ErrorAction Ignore; "
            "Remove-Item Env:_CE_M -ErrorAction Ignore; "
            "Clear-Host;"
            'function prompt {"(hrl) " + $(Get-Location) + "> "};'
        )

        print(f"--- Launching standalone terminal ({shell}) ---")
        cmd = [shell, "-NoExit", "-Command", clear_conda_ps]
        subprocess.run(
            cmd,
            env=backend_env,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr
        )

    else:
        # Linux/Mac

        # Define your custom prompt
        custom_prompt = r'\[\033[01;33m\](hrl)\[\033[00m\] \[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '

        # Path to temporary bashrc
        temp_rc = '/tmp/.custom_bashrc'
        original_bashrc = os.path.expanduser('~/.bashrc')

        # Copy the original bashrc and append PS1 override
        try:
            if os.path.exists(original_bashrc):
                with open(original_bashrc, 'r') as src:
                    bashrc_content = src.read()
            else:
                print(f"⚠️  Warning: {original_bashrc} not found, starting with empty config")
                bashrc_content = ""

            with open(temp_rc, 'w') as dst:
                # Write original bashrc content
                dst.write(bashrc_content)
            # Deactivate conda if it was activated, then set custom PS1
                dst.write(f"""
# Deactivate conda environment if active
if command -v conda &> /dev/null; then
    conda deactivate 2>/dev/null || true
fi

# Custom PS1 override
export PS1='{custom_prompt}'
""")

        except Exception as e:
            print(f"🚨 Error creating temporary bashrc: {e}", file=sys.stderr)
            sys.exit(1)

        # Set up environment
        shell = os.environ.get("SHELL", "/bin/bash")

        # Use --rcfile to load our custom rc instead of ~/.bashrc
        args = [shell, "--rcfile", temp_rc, "-i"]

        print(f"--- hrl custom environment ---")
        print()


        # os.execvpe replaces the current Python process with the shell
        # If this fails, it throws an exception (it doesn't return)
        try:
            os.execvpe(shell, args, env=backend_env)
        except OSError as e:
            print(f"🚨 Failed to execute shell: {e}")

    print("\n--- Exited standalone environment ---")

