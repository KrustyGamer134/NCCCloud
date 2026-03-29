from __future__ import annotations

import io
import zipfile

from core.steamcmd import install_windows_bootstrap, probe_steamcmd_executable


def _steamcmd_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("steamcmd.exe", "stub")
        archive.writestr("steam.dll", "stub")
    return buf.getvalue()


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _SubprocessSuccess:
    STDOUT = object()
    PIPE = object()

    class TimeoutExpired(Exception):
        pass

    class STARTUPINFO:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = 0

    STARTF_USESHOWWINDOW = 1
    SW_HIDE = 0

    def __init__(self, *, returncode: int = 0, stdout_text: str = "Loading Steam API...OK\n"):
        self.calls = []
        self._returncode = int(returncode)
        self._stdout_text = str(stdout_text)

    class _Proc:
        class _Stdout:
            def __init__(self, text: str):
                self._lines = [line + "\n" for line in str(text or "").splitlines()]
                self._index = 0

            def readline(self):
                if self._index >= len(self._lines):
                    return ""
                value = self._lines[self._index]
                self._index += 1
                return value

            def read(self):
                if self._index >= len(self._lines):
                    return ""
                value = "".join(self._lines[self._index :])
                self._index = len(self._lines)
                return value

            def close(self):
                return None

        def __init__(self, *, returncode: int, stdout_text: str, stdout_handle=None):
            self.returncode = int(returncode)
            self.stdout = self._Stdout(stdout_text)
            self._stdout_handle = stdout_handle
            self._stdout_text = stdout_text

        def poll(self):
            if self.stdout._index >= len(self.stdout._lines):
                return self.returncode
            return None

        def communicate(self, timeout=None):
            if self._stdout_handle is not None and self._stdout_text:
                self._stdout_handle.write(self._stdout_text)
                self._stdout_handle.flush()
            self.stdout._index = len(self.stdout._lines)
            return ("", "")

        def wait(self, timeout=None):
            self.stdout._index = len(self.stdout._lines)
            return self.returncode

        def kill(self):
            self.stdout._index = len(self.stdout._lines)
            return None

    def Popen(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "shell": shell,
                "stdout": stdout,
                "stderr": stderr,
                "startupinfo": startupinfo,
                "kwargs": kwargs,
            }
        )
        return self._Proc(returncode=self._returncode, stdout_text=self._stdout_text, stdout_handle=stdout)


def test_install_windows_bootstrap_requires_root():
    out = install_windows_bootstrap("")
    assert out["ok"] is False
    assert "SteamCMD Root" in out["message"]


def test_install_windows_bootstrap_extracts_steamcmd(tmp_path):
    subprocess_stub = _SubprocessSuccess()
    out = install_windows_bootstrap(
        str(tmp_path),
        urlopen_fn=lambda url: _Response(_steamcmd_zip_bytes()),
        subprocess_module=subprocess_stub,
    )

    assert out["ok"] is True
    assert (tmp_path / "steamcmd.exe").is_file()
    assert out["steamcmd_exe"] == str(tmp_path / "steamcmd.exe")
    assert out["installed_now"] is True
    assert [call["argv"] for call in subprocess_stub.calls] == [
        [str(tmp_path / "steamcmd.exe"), "+quit"],
        [str(tmp_path / "steamcmd.exe"), "+login", "anonymous", "+quit"],
    ]


def test_install_windows_bootstrap_reports_existing_exe(tmp_path):
    exe_path = tmp_path / "steamcmd.exe"
    exe_path.write_text("stub", encoding="utf-8")

    subprocess_stub = _SubprocessSuccess()
    out = install_windows_bootstrap(str(tmp_path), subprocess_module=subprocess_stub)

    assert out["ok"] is True
    assert out["message"] == "SteamCMD already available."
    assert out["installed_now"] is False
    assert [call["argv"] for call in subprocess_stub.calls] == [
        [str(exe_path), "+quit"],
        [str(exe_path), "+login", "anonymous", "+quit"],
    ]


def test_install_windows_bootstrap_fails_when_bootstrap_probe_fails(tmp_path):
    out = install_windows_bootstrap(
        str(tmp_path),
        urlopen_fn=lambda url: _Response(_steamcmd_zip_bytes()),
        subprocess_module=_SubprocessSuccess(returncode=7),
    )

    assert out["ok"] is False
    assert out["message"] == "SteamCMD bootstrap failed: steamcmd exited with code 7."


def test_install_windows_bootstrap_accepts_loading_steam_api_ok_as_success(tmp_path):
    out = install_windows_bootstrap(
        str(tmp_path),
        urlopen_fn=lambda url: _Response(_steamcmd_zip_bytes()),
        subprocess_module=_SubprocessSuccess(returncode=0, stdout_text="Loading Steam API...OK\n"),
    )

    assert out["ok"] is True
    assert out["message"] == "SteamCMD installed successfully."
    assert out["installed_now"] is True


def test_install_windows_bootstrap_fails_on_error_marker_even_with_zero_exit(tmp_path):
    out = install_windows_bootstrap(
        str(tmp_path),
        urlopen_fn=lambda url: _Response(_steamcmd_zip_bytes()),
        subprocess_module=_SubprocessSuccess(returncode=0, stdout_text="ERROR! Failed to install app\n"),
    )

    assert out["ok"] is False
    assert out["message"] == "SteamCMD bootstrap failed: ERROR! Failed to install app"


def test_probe_steamcmd_executable_reports_missing_exe(tmp_path):
    result = probe_steamcmd_executable(str(tmp_path / "steamcmd.exe"))

    assert result["ok"] is False
    assert "SteamCMD is missing" in str(result["error_reason"] or "")
