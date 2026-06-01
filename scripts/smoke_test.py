#!/usr/bin/env python3
"""
IndITR smoke test — exercises every non-LLM endpoint plus file upload.

Usage:
    python scripts/smoke_test.py                       # http://localhost:8000
    python scripts/smoke_test.py --base-url http://localhost:8000
    docker compose run --rm api python scripts/smoke_test.py

What it tests (in order):
    1. GET  /health                        — API is up
    2. GET  /                              — root JSON
    3. POST /session/start                 — create session, get session_id
    4. GET  /session/{id}                  — initial state
    5. POST /session/{id}/upload (CSV)     — Zerodha P&L CSV parsed correctly
    6. POST /session/{id}/upload (XLSX)    — minimal XLSX doesn't crash
    7. GET  /session/{id}                  — documents_uploaded == 2
    8. GET  /session/{id}/outputs          — outputs endpoint returns JSON
    9. POST /session/{id}/confirm (false)  — confirm endpoint reachable
   10. POST /session/{id}/message          — chat endpoint reachable (may need LLM)

Exit codes:
    0  all tests passed
    1  one or more tests failed
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import sys
import textwrap
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# ── colour helpers ────────────────────────────────────────────────────────────
_RESET  = "\033[0m"
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"

def _ok(msg: str)   -> None: print(f"  {_GREEN}[OK]{_RESET} {msg}")
def _fail(msg: str) -> None: print(f"  {_RED}[FAIL]{_RESET} {msg}")
def _warn(msg: str) -> None: print(f"  {_YELLOW}[WARN]{_RESET} {msg}")
def _head(msg: str) -> None: print(f"\n{_BOLD}{_CYAN}{msg}{_RESET}")


# ── HTTP helpers (stdlib only — no requests dependency) ──────────────────────

def _req(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str | None = "application/json",
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any] | str]:
    """Make an HTTP request; return (status_code, parsed_body)."""
    h: dict[str, str] = {}
    if content_type:
        h["Content-Type"] = content_type
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _json_req(method: str, url: str, payload: dict | None = None, **kw):
    body = json.dumps(payload).encode() if payload is not None else None
    return _req(method, url, body=body, **kw)


def _multipart_upload(url: str, filename: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> tuple[int, dict]:
    """POST multipart/form-data with a single 'file' field."""
    boundary = b"----InditrSmokeTestBoundary"
    body = (
        b"--" + boundary + b"\r\n"
        + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
        + f"Content-Type: {content_type}\r\n\r\n".encode()
        + file_bytes
        + b"\r\n--" + boundary + b"--\r\n"
    )
    ct = f"multipart/form-data; boundary={boundary.decode()}"
    return _req("POST", url, body=body, content_type=ct, timeout=60)


# ── Synthetic test documents ──────────────────────────────────────────────────

def _zerodha_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    # Matches the format the parser's _find_header_row expects:
    # header on the first row, trades immediately after.
    w.writerow(["Symbol", "ISIN", "Buy Date", "Sell Date",
                "Buy Value", "Sell Value", "STCG", "LTCG", "Quantity"])
    w.writerow(["RELIANCE", "INE002A01018", "01/04/2023", "15/03/2024",
                "100000", "120000", "20000", "0", "100"])
    w.writerow(["HDFCBANK",  "INE040A01034", "01/01/2022", "01/06/2023",
                "200000", "250000", "0", "50000", "50"])
    return buf.getvalue().encode()


def _minimal_xlsx() -> bytes:
    """Smallest valid XLSX (via openpyxl if available, else stub bytes)."""
    try:
        import openpyxl, io as _io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Name", "Value"])
        ws.append(["test", 42])
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        # Return a 4-byte stub — the parser will fail gracefully and return parse_errors
        return b"PK\x03\x04"


# ── Test runner ───────────────────────────────────────────────────────────────

class SmokeTest:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.passed = 0
        self.failed = 0
        self.session_id: str | None = None

    def _assert(self, label: str, condition: bool, detail: str = "") -> bool:
        if condition:
            _ok(label)
            self.passed += 1
            return True
        else:
            _fail(f"{label}" + (f" — {detail}" if detail else ""))
            self.failed += 1
            return False

    # ── individual tests ──────────────────────────────────────────────────────

    def test_health(self):
        _head("1. Health check")
        status, body = _json_req("GET", f"{self.base}/health")
        self._assert("HTTP 200", status == 200, f"got {status}")
        if isinstance(body, dict):
            self._assert('status == "ok"', body.get("status") == "ok", str(body))
            self._assert("assessment_year present", "assessment_year" in body)

    def test_root(self):
        _head("2. Root endpoint")
        status, body = _json_req("GET", f"{self.base}/")
        self._assert("HTTP 200", status == 200)
        if isinstance(body, dict):
            self._assert('"name" field present', "name" in body)
            self._assert('"disclaimer" field present', "disclaimer" in body)

    def test_session_start(self):
        _head("3. Session start")
        status, body = _json_req(
            "POST", f"{self.base}/session/start",
            {"assessment_year": "AY2026-27"},
        )
        self._assert("HTTP 200", status == 200)
        if isinstance(body, dict) and "session_id" in body:
            self.session_id = body["session_id"]
            self._assert("session_id non-empty", bool(self.session_id))
        else:
            _fail(f"No session_id in response: {body}")
            self.failed += 1

    def test_session_get(self):
        _head("4. Get session")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        status, body = _json_req("GET", f"{self.base}/session/{self.session_id}")
        self._assert("HTTP 200", status == 200)
        if isinstance(body, dict):
            self._assert('"current_act" present', "current_act" in body)
            self._assert('initial act is "collect_profile"',
                         body.get("current_act") == "collect_profile",
                         f"got {body.get('current_act')}")
            self._assert('"documents_uploaded" == 0',
                         body.get("documents_uploaded") == 0)

    def test_upload_csv(self):
        _head("5. Upload Zerodha CSV")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        url = f"{self.base}/session/{self.session_id}/upload"
        status, body = _multipart_upload(
            url, "zerodha_pnl.csv", _zerodha_csv(), "text/csv"
        )
        self._assert("HTTP 200", status == 200, str(body)[:200])
        if isinstance(body, dict):
            self._assert(
                'doc_type contains "zerodha"',
                "zerodha" in (body.get("doc_type") or "").lower(),
                f"got doc_type={body.get('doc_type')!r}",
            )
            self._assert(
                "fields_extracted > 0",
                (body.get("fields_extracted") or 0) > 0,
            )
            errors = body.get("parse_errors", [])
            if errors:
                _warn(f"parse_errors (non-fatal): {errors}")

    def test_upload_xlsx(self):
        _head("6. Upload minimal XLSX (should not crash)")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        url = f"{self.base}/session/{self.session_id}/upload"
        status, body = _multipart_upload(
            url, "generic.xlsx", _minimal_xlsx(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        # We just want the API to not 500 — even parse_errors is fine
        self._assert("HTTP 200 (no crash)", status == 200, str(body)[:200])
        if isinstance(body, dict):
            self._assert("response has doc_type key", "doc_type" in body)

    def test_session_has_docs(self):
        _head("7. Session shows 2 uploaded documents")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        status, body = _json_req("GET", f"{self.base}/session/{self.session_id}")
        self._assert("HTTP 200", status == 200)
        if isinstance(body, dict):
            count = body.get("documents_uploaded", 0)
            self._assert("documents_uploaded == 2", count == 2, f"got {count}")

    def test_outputs(self):
        _head("8. Outputs endpoint (pre-compute state)")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        status, body = _json_req("GET", f"{self.base}/session/{self.session_id}/outputs")
        self._assert("HTTP 200", status == 200)
        if isinstance(body, dict):
            self._assert('"ready" key present', "ready" in body)
            # Computation hasn't run yet — ready may be False, that's fine
            _ok(f'ready={body.get("ready")}  (computation not triggered yet)')

    def test_confirm(self):
        _head("9. Confirm endpoint (confirmed=false)")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        status, body = _json_req(
            "POST", f"{self.base}/session/{self.session_id}/confirm",
            {"confirmed": False},
        )
        self._assert("HTTP 200", status == 200, str(body)[:200])
        if isinstance(body, dict):
            self._assert(
                "confirmed == False in response",
                body.get("confirmed") is False,
            )

    def test_chat(self):
        _head("10. Chat message (LLM — 90 s timeout)")
        if not self.session_id:
            _warn("Skipped — no session_id")
            return
        import urllib.error as _ue
        try:
            status, body = _json_req(
                "POST", f"{self.base}/session/{self.session_id}/message",
                {"role": "user", "message": "Hello, I am a salaried employee."},
                timeout=90,   # LLM calls can be slow on first request
            )
        except (_ue.URLError, TimeoutError) as exc:
            _warn(f"Chat timed out / unreachable: {exc}")
            _warn("LLM may still be cold-starting — retry manually")
            return  # not counted as pass or fail

        self._assert("HTTP 200", status == 200, str(body)[:200])
        if isinstance(body, dict):
            reply = body.get("assistant_message", "")
            if reply and "error" not in reply.lower()[:20]:
                _ok(f"LLM responded ({len(reply)} chars)")
            else:
                _warn(
                    f"LLM may not be running — reply: {reply[:120]!r}\n"
                    "  Run: docker compose run model-init   to pull models"
                )

    # ── orchestration ─────────────────────────────────────────────────────────

    def run(self):
        print(f"\n{_BOLD}IndITR Smoke Test{_RESET}  ->  {self.base}\n" + "-" * 60)
        try:
            self.test_health()
            self.test_root()
            self.test_session_start()
            self.test_session_get()
            self.test_upload_csv()
            self.test_upload_xlsx()
            self.test_session_has_docs()
            self.test_outputs()
            self.test_confirm()
            self.test_chat()
        except Exception:
            print(f"\n{_RED}Unexpected error:{_RESET}")
            traceback.print_exc()
            self.failed += 1

        total = self.passed + self.failed
        colour = _GREEN if self.failed == 0 else _RED
        print(f"\n{'-' * 60}")
        print(
            f"{_BOLD}Result: "
            f"{colour}{self.passed}/{total} passed{_RESET}"
            + (f"  ({self.failed} failed)" if self.failed else "")
        )
        return self.failed == 0


def main():
    parser = argparse.ArgumentParser(description="IndITR smoke test")
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)"
    )
    args = parser.parse_args()

    ok = SmokeTest(args.base_url).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
