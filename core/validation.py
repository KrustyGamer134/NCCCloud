from __future__ import annotations

from typing import Dict, List, Optional, cast


def make_validation_check(check_id: str, ok: bool, details: str) -> Dict[str, object]:
    return {"id": str(check_id), "ok": bool(ok), "details": str(details)}


def normalize_validation_result(
    *,
    ok: bool = False,
    checks: Optional[List[dict]] = None,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, object]:
    return {
        "ok": bool(ok),
        "checks": list(checks or []),
        "warnings": [str(item) for item in list(warnings or [])],
        "errors": [str(item) for item in list(errors or [])],
    }


def make_validation_result() -> Dict[str, object]:
    return normalize_validation_result(ok=False, checks=[], warnings=[], errors=[])


def add_validation_check(result: Dict[str, object], check_id: str, ok: bool, details: str) -> Dict[str, object]:
    checks = cast(List[dict], result.setdefault("checks", []))
    checks.append(make_validation_check(check_id, ok, details))
    return result


def add_validation_warning(result: Dict[str, object], warning: str) -> Dict[str, object]:
    warnings = cast(List[str], result.setdefault("warnings", []))
    warnings.append(str(warning))
    return result


def add_validation_error(result: Dict[str, object], error: str) -> Dict[str, object]:
    errors = cast(List[str], result.setdefault("errors", []))
    errors.append(str(error))
    return result


def finalize_validation_result(result: Dict[str, object]) -> Dict[str, object]:
    raw_checks = result.get("checks")
    raw_warnings = result.get("warnings")
    raw_errors = result.get("errors")
    checks = list(raw_checks) if isinstance(raw_checks, list) else []
    warnings = [str(item) for item in raw_warnings] if isinstance(raw_warnings, list) else []
    errors = [str(item) for item in raw_errors] if isinstance(raw_errors, list) else []
    return normalize_validation_result(ok=(len(errors) == 0), checks=checks, warnings=warnings, errors=errors)


def validation_response_status(result: Dict[str, object]) -> str:
    return "success" if bool(result.get("ok")) else "error"
