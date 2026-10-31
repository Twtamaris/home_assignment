#!/usr/bin/env python3
"""
Cross-platform CLI task runner for Multi-Tenant Agent Platform.
Provides equivalent functionality to Makefile for environments without `make`.
Usage:
  python run.py seed
  python run.py eval
  python run.py test
  python run.py advance-order <ORDER_ID> <STATUS>
  python run.py backend
  python run.py frontend
"""
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

def get_python_bin():
    # Check venv
    win_bin = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    if win_bin.exists():
        return str(win_bin)
    unix_bin = BACKEND_DIR / ".venv" / "bin" / "python"
    if unix_bin.exists():
        return str(unix_bin)
    return sys.executable

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    py = get_python_bin()

    if cmd == "seed":
        sys.exit(subprocess.run([py, str(BACKEND_DIR / "scripts" / "seed.py")]).returncode)
    elif cmd == "eval":
        sys.exit(subprocess.run([py, str(BACKEND_DIR / "scripts" / "run_eval.py")]).returncode)
    elif cmd == "test":
        sys.exit(subprocess.run([py, "-m", "pytest", str(BACKEND_DIR / "tests" / "test_tenant_isolation.py"), "-v"]).returncode)
    elif cmd == "advance-order":
        if len(sys.argv) < 4:
            print("Usage: python run.py advance-order <ORDER_ID> <confirmed|shipped|delivered|cancelled>")
            sys.exit(1)
        sys.exit(subprocess.run([py, str(BACKEND_DIR / "scripts" / "advance_order.py"), sys.argv[2], sys.argv[3]]).returncode)
    elif cmd == "backend":
        sys.exit(subprocess.run([py, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], cwd=str(BACKEND_DIR)).returncode)
    elif cmd == "frontend":
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        sys.exit(subprocess.run([npm_cmd, "run", "dev"], cwd=str(FRONTEND_DIR)).returncode)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
