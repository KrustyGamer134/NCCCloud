from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

STEAMCMD_WINDOWS_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
_STEAMCMD_FAILURE_MARKERS = (
    "ERROR!",
    "Missing configuration",
    "Failed to install app",
)


def startupinfo(*, is_windows_fn, subprocess_module):
    if not is_windows_fn() or not hasattr(subprocess_module, "STARTUPINFO"):
        return None
    info = subprocess_module.STARTUPINFO()
    info.dwFlags |= getattr(subprocess_module, "STARTF_USESHOWWINDOW", 0)
    info.wShowWindow = getattr(subprocess_module, "SW_HIDE", 0)
    return info


def run_command(
    argv,
    *,
    cwd,
    stdout_path: str,
    timeout_seconds: float,
    startupinfo,
    subprocess_module,
    timeout_kill_wait_seconds: float = 5.0,
    on_output_line=None,
    stream_output: bool = False,
):
    proc = None
    try:
        with open(stdout_path, "w", encoding="utf-8") as stdout_handle:
            if not stream_output:
                proc = subprocess_module.Popen(
                    list(argv),
                    cwd=cwd,
                    shell=False,
                    stdout=stdout_handle,
                    stderr=subprocess_module.STDOUT,
                    startupinfo=startupinfo,
                )
                proc.communicate(timeout=timeout_seconds)
                return int(proc.returncode)
            proc = subprocess_module.Popen(
                list(argv),
                cwd=cwd,
                shell=False,
                stdout=subprocess_module.PIPE,
                stderr=subprocess_module.STDOUT,
                startupinfo=startupinfo,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            deadline = time.monotonic() + float(timeout_seconds)
            while True:
                if time.monotonic() >= deadline:
                    raise subprocess_module.TimeoutExpired(list(argv), timeout_seconds)
                line = proc.stdout.readline()
                if line:
                    stdout_handle.write(line)
                    stdout_handle.flush()
                    if callable(on_output_line):
                        on_output_line(line.rstrip("\r\n"))
                    continue
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            remainder = proc.stdout.read() if proc.stdout is not None else ""
            if remainder:
                stdout_handle.write(remainder)
                stdout_handle.flush()
                if callable(on_output_line):
                    for raw_line in str(remainder).splitlines():
                        on_output_line(raw_line)
        return int(proc.returncode)
    except subprocess_module.TimeoutExpired:
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=timeout_kill_wait_seconds)
        raise
    finally:
        if proc is not None and getattr(proc, "stdout", None) is not None:
            with contextlib.suppress(Exception):
                proc.stdout.close()


def _read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except Exception:
        return ""


def _bootstrap_success_detected(stdout_text: str) -> bool:
    text = str(stdout_text or "")
    return "Loading Steam API...OK" in text or "Verification complete" in text


def _steamcmd_output_failure_reason(output_text: str):
    text = str(output_text or "")
    for raw_line in text.splitlines():
        line = str(raw_line).strip()
        if not line:
            continue
        for marker in _STEAMCMD_FAILURE_MARKERS:
            if marker.lower() in line.lower():
                return line
    return None


def _probe_failure_message(probe_result: dict) -> str:
    reason = str(probe_result.get("error_reason") or "").strip()
    rc = probe_result.get("returncode")
    if reason:
        return f"SteamCMD bootstrap failed: {reason}"
    if rc is None:
        return "SteamCMD bootstrap failed."
    return f"SteamCMD bootstrap failed: steamcmd exited with code {int(rc)}."


def _run_probe_command(
    exe_path: str,
    argv,
    *,
    log_name: str,
    subprocess_module,
    is_windows_fn,
    timeout_seconds: float,
):
    stdout_path = os.path.join(os.path.dirname(exe_path), log_name)
    try:
        rc = run_command(
            list(argv),
            cwd=os.path.dirname(exe_path) or None,
            stdout_path=stdout_path,
            timeout_seconds=timeout_seconds,
            startupinfo=startupinfo(is_windows_fn=is_windows_fn, subprocess_module=subprocess_module),
            subprocess_module=subprocess_module,
        )
    except subprocess_module.TimeoutExpired:
        return {"ok": False, "returncode": None, "output": "", "error_reason": f"timed out after {timeout_seconds}s."}
    except Exception as exc:
        return {"ok": False, "returncode": None, "output": "", "error_reason": str(exc)}

    stdout_text = _read_text_file(stdout_path)
    failure_reason = _steamcmd_output_failure_reason(stdout_text)
    if failure_reason:
        return {"ok": False, "returncode": int(rc), "output": stdout_text, "error_reason": failure_reason}
    if int(rc) != 0:
        return {"ok": False, "returncode": int(rc), "output": stdout_text, "error_reason": f"steamcmd exited with code {int(rc)}."}
    if not _bootstrap_success_detected(stdout_text):
        return {"ok": False, "returncode": int(rc), "output": stdout_text, "error_reason": "missing success marker in SteamCMD output."}
    return {"ok": True, "returncode": int(rc), "output": stdout_text, "error_reason": None}


def warmup_steamcmd_executable(
    steamcmd_exe: str,
    *,
    subprocess_module=subprocess,
    is_windows_fn=lambda: os.name == "nt",
    timeout_seconds: float = 60.0,
):
    exe_path = str(steamcmd_exe or "").strip()
    if not exe_path or not os.path.isfile(exe_path):
        return {"ok": False, "returncode": None, "output": "", "error_reason": f"SteamCMD is missing: {exe_path}"}
    return _run_probe_command(
        exe_path,
        [exe_path, "+login", "anonymous", "+quit"],
        log_name="steamcmd_warmup.log",
        subprocess_module=subprocess_module,
        is_windows_fn=is_windows_fn,
        timeout_seconds=timeout_seconds,
    )


def install_windows_bootstrap(
    steamcmd_root: str,
    *,
    url: str = STEAMCMD_WINDOWS_ZIP_URL,
    urlopen_fn=None,
    zipfile_module=zipfile,
    tempfile_module=tempfile,
    shutil_module=shutil,
    subprocess_module=subprocess,
    is_windows_fn=lambda: os.name == "nt",
    bootstrap_timeout_seconds: float = 60.0,
):
    raw_root = str(steamcmd_root or "").strip()
    if not raw_root:
        return {"ok": False, "message": "SteamCMD Root is not configured in App Settings."}
    root = os.path.abspath(raw_root)

    exe_path = os.path.join(root, "steamcmd.exe")
    if os.path.isfile(exe_path):
        probe_result = probe_steamcmd_executable(
            exe_path,
            subprocess_module=subprocess_module,
            is_windows_fn=is_windows_fn,
            timeout_seconds=bootstrap_timeout_seconds,
        )
        if probe_result.get("ok") is not True:
            return {"ok": False, "message": _probe_failure_message(probe_result)}
        warmup_result = warmup_steamcmd_executable(
            exe_path,
            subprocess_module=subprocess_module,
            is_windows_fn=is_windows_fn,
            timeout_seconds=bootstrap_timeout_seconds,
        )
        if warmup_result.get("ok") is not True:
            return {"ok": False, "message": _probe_failure_message(warmup_result)}
        return {
            "ok": True,
            "message": "SteamCMD already available.",
            "steamcmd_root": root,
            "steamcmd_exe": exe_path,
            "installed_now": False,
        }

    os.makedirs(root, exist_ok=True)
    opener = urlopen_fn or urllib.request.urlopen
    temp_dir = tempfile_module.mkdtemp(prefix="ncc-steamcmd-")
    extract_dir = os.path.join(temp_dir, "extract")
    try:
        with opener(url) as response:
            payload = response.read()

        os.makedirs(extract_dir, exist_ok=True)
        with zipfile_module.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(extract_dir)

        extracted_exe = os.path.join(extract_dir, "steamcmd.exe")
        if not os.path.isfile(extracted_exe):
            return {"ok": False, "message": "SteamCMD bootstrap archive did not contain steamcmd.exe."}

        for name in os.listdir(extract_dir):
            src = os.path.join(extract_dir, name)
            dst = os.path.join(root, name)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil_module.rmtree(dst)
                shutil_module.copytree(src, dst)
            else:
                shutil_module.copy2(src, dst)

        if not os.path.isfile(exe_path):
            return {"ok": False, "message": "SteamCMD bootstrap completed but steamcmd.exe was not created."}

        probe_result = probe_steamcmd_executable(
            exe_path,
            subprocess_module=subprocess_module,
            is_windows_fn=is_windows_fn,
            timeout_seconds=bootstrap_timeout_seconds,
        )
        if probe_result.get("ok") is not True:
            return {"ok": False, "message": _probe_failure_message(probe_result)}

        warmup_result = warmup_steamcmd_executable(
            exe_path,
            subprocess_module=subprocess_module,
            is_windows_fn=is_windows_fn,
            timeout_seconds=bootstrap_timeout_seconds,
        )
        if warmup_result.get("ok") is not True:
            return {"ok": False, "message": _probe_failure_message(warmup_result)}
        return {
            "ok": True,
            "message": "SteamCMD installed successfully.",
            "steamcmd_root": root,
            "steamcmd_exe": exe_path,
            "installed_now": True,
        }
    except Exception as e:
        return {"ok": False, "message": f"SteamCMD install failed: {e}"}
    finally:
        with contextlib.suppress(Exception):
            shutil_module.rmtree(temp_dir)


def probe_steamcmd_executable(
    steamcmd_exe: str,
    *,
    subprocess_module=subprocess,
    is_windows_fn=lambda: os.name == "nt",
    timeout_seconds: float = 60.0,
):
    exe_path = str(steamcmd_exe or "").strip()
    if not exe_path:
        return {"ok": False, "returncode": None, "output": "", "error_reason": "SteamCMD is not installed yet."}
    if not os.path.isfile(exe_path):
        return {"ok": False, "returncode": None, "output": "", "error_reason": f"SteamCMD is missing: {exe_path}"}

    return _run_probe_command(
        exe_path,
        [exe_path, "+quit"],
        log_name="steamcmd_bootstrap.log",
        subprocess_module=subprocess_module,
        is_windows_fn=is_windows_fn,
        timeout_seconds=timeout_seconds,
    )
