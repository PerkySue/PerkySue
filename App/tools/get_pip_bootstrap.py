"""
Bootstrap pip for embedded Python.
Uses only stdlib - no external dependencies.
"""
import os
import subprocess
import sys
import tempfile
import urllib.request

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

def main():
    tmp = os.path.join(tempfile.gettempdir(), "get-pip.py")

    print("  Downloading get-pip.py...")
    try:
        urllib.request.urlretrieve(GET_PIP_URL, tmp)
        print("  [OK] Downloaded.")
    except Exception as e:
        print(f"  [ERROR] Download failed: {e}")
        print(f"  Try downloading manually: {GET_PIP_URL}")
        sys.exit(1)

    if not os.path.exists(tmp):
        print("  [ERROR] File not saved!")
        sys.exit(1)

    print(f"  Running get-pip.py...")
    try:
        result = subprocess.run(
            [sys.executable, tmp, "--no-warn-script-location"],
            check=False
        )
        if result.returncode != 0:
            print(f"  [WARN] get-pip exited with code {result.returncode}")
    except Exception as e:
        print(f"  [ERROR] Failed to run get-pip.py: {e}")
        sys.exit(1)

    try:
        os.remove(tmp)
    except OSError:
        pass

    print("  [OK] pip bootstrap complete.")

if __name__ == "__main__":
    main()
