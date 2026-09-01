"""Validate that eit_ptlc carries its hardware driver runtime resources."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DRIVER_DIR = Path(__file__).resolve().parent
NATIVE_DIR = DRIVER_DIR / "gxipy" / "native" / "win64"


def _record(ok: bool, label: str, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")
    return ok


def _check_file(path: Path, label: str) -> bool:
    return _record(path.is_file(), label, str(path))


def _check_dir(path: Path, label: str) -> bool:
    return _record(path.is_dir(), label, str(path))


def _scan_external_refs() -> bool:
    patterns = (
        "View/dahengCamera",
        "GALAXY_GENICAM_ROOT",
        "unilabos迁移",
        "液位检测模块/work",
    )
    suffixes = {".py", ".yaml", ".yml", ".json", ".toml", ".md", ".sh"}
    hits: list[str] = []
    self_path = Path(__file__).resolve()
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == self_path:
            continue
        if any(part in {"__pycache__", "node_modules"} for part in path.parts):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            if pattern in text:
                rel = path.relative_to(PACKAGE_ROOT)
                hits.append(f"{rel}: {pattern}")
    if hits:
        return _record(False, "no external driver path references", "; ".join(hits[:10]))
    return _record(True, "no external driver path references")


def _check_imports() -> bool:
    if str(DRIVER_DIR) not in sys.path:
        sys.path.insert(0, str(DRIVER_DIR))
    try:
        gxipy = importlib.import_module("gxipy")
    except Exception as exc:
        return _record(False, "import gxipy from vendored SDK", repr(exc))
    ok = _record(True, "import gxipy from vendored SDK", str(Path(gxipy.__file__).resolve()))

    try:
        module = importlib.import_module("eit_ptlc.driver.daheng_capture")
    except Exception as exc:
        return _record(False, "import daheng_capture", repr(exc)) and ok
    return _record(True, "import daheng_capture", str(Path(module.__file__).resolve())) and ok


def main() -> int:
    checks = [
        _check_dir(NATIVE_DIR / "apidll", "Daheng APIDll directory"),
        _check_dir(NATIVE_DIR / "genicam", "Daheng GenICam directory"),
        _check_dir(NATIVE_DIR / "gentl", "Daheng GenTL directory"),
        _check_file(NATIVE_DIR / "apidll" / "GxIAPI.dll", "GxIAPI.dll"),
        _check_file(NATIVE_DIR / "apidll" / "DxImageProc.dll", "DxImageProc.dll"),
        _check_file(NATIVE_DIR / "gentl" / "GxGVTL.cti", "GigE GenTL producer"),
        _check_file(DRIVER_DIR / "dobot_tcp_v4" / "files" / "alarmController.json", "Dobot controller alarm table"),
        _check_file(DRIVER_DIR / "dobot_tcp_v4" / "files" / "alarmServo.json", "Dobot servo alarm table"),
        _check_file(DRIVER_DIR / "water_level_payload" / "run.sh", "water-level run.sh"),
        _check_file(DRIVER_DIR / "water_level_payload" / "water_level_8ch_compress_mqtt.py", "water-level service script"),
        _scan_external_refs(),
        _check_imports(),
    ]
    if all(checks):
        print("Driver bundle check passed.")
        return 0
    print("Driver bundle check failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
