import subprocess
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER_URL = "http://127.0.0.1:8000"


def ensure_server_running():
    try:
        import urllib.request

        with urllib.request.urlopen(SERVER_URL, timeout=2):
            return True
    except Exception:
        return False


def start_server():
    if ensure_server_running():
        return

    cmd = [str(VENV_PYTHON), "manage.py", "runserver", "0.0.0.0:8000"]
    subprocess.Popen(cmd, cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
    for _ in range(30):
        time.sleep(0.5)
        if ensure_server_running():
            return
    raise RuntimeError("The Django app did not start in time.")


def show_login_info():
    print("\n========================================")
    print("Bookish Lamp Demo Login")
    print("========================================")
    print("username: admin")
    print("password: demo12345")
    print("URL: http://127.0.0.1:8000")
    print("========================================\n")


def main():
    try:
        start_server()
        show_login_info()
        webbrowser.open(SERVER_URL)
        print("The app is opening in your browser.")
    except Exception as exc:
        print(f"Launcher error: {exc}")
        input("Press Enter to exit...")
        raise


if __name__ == "__main__":
    main()
