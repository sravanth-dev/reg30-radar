"""A thin wrapper over the Google Sheets v4 REST API - just enough for sync.py's needs.

Deliberately not `gspread` or `google-api-python-client` - neither is on the approved
dependency list (ARCHITECTURE.md Sect.9). `google-auth`'s `AuthorizedSession` is an
ordinary `requests.Session` that refreshes its own bearer token, so every call below is a
plain HTTP request, readable end to end and easy to fake in tests without a real service
account or any network access.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from urllib.parse import quote

# A plain signed/unsigned decimal, nothing else - what write_numbers() will accept before
# it lets a value anywhere near USER_ENTERED (see that method).
_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(RuntimeError):
    """A Sheets API call failed. Carries the response body - the API's error messages are
    specific enough to act on (a missing scope reads differently from a missing tab), and
    swallowing them would turn every failure into a guessing game."""


def authorized_session(key_file: str):
    """A `requests`-compatible session authenticated as the service account in `key_file`.

    Imported lazily, so importing this module - which every test does, via a fake session
    - never requires google-auth to be configured with real credentials.
    """
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    return AuthorizedSession(creds)


def _col_letter(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA. Sheets' column-letter convention (base-26, no zero)."""
    letters = string.ascii_uppercase
    out: list[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out.append(letters[rem])
    return "".join(reversed(out))


def _raise_for_status(response) -> None:
    if response.status_code >= 300:
        raise SheetsError(f"Sheets API {response.status_code}: {response.text[:500]}")


@dataclass
class SheetsClient:
    """Talks to one tab of one spreadsheet. `session` is anything with .get/.post/.put -
    an `AuthorizedSession` in production, a fake in tests."""

    session: object
    spreadsheet_id: str
    tab_name: str
    api_base: str = API_BASE
    _sheet_id: int | None = field(default=None, init=False, repr=False)

    def _url(self, suffix: str = "") -> str:
        return f"{self.api_base}/{self.spreadsheet_id}{suffix}"

    def _a1(self, range_in_tab: str) -> str:
        # Single-quoted so a tab name containing a space still parses as one token.
        return f"'{self.tab_name}'!{range_in_tab}"

    def _all_sheets(self, extra_fields: str = "") -> list[dict]:
        # Both extras must nest inside the same `sheets(...)` selector - "sheets.properties,
        # protectedRanges" parses as two top-level fields, and protectedRanges only exists
        # per-sheet, not at the spreadsheet's top level, so the API rejects it outright.
        # This lists every tab, so - unlike _properties() below - it works even before
        # this client's own tab exists, which is what ensure_tab() needs.
        inner = "properties" + (f",{extra_fields}" if extra_fields else "")
        fields = f"sheets({inner})"
        r = self.session.get(self._url(), params={"fields": fields})
        _raise_for_status(r)
        return r.json().get("sheets", [])

    def _properties(self, extra_fields: str = "") -> dict:
        for sheet in self._all_sheets(extra_fields):
            if sheet["properties"]["title"] == self.tab_name:
                return sheet
        raise SheetsError(
            f"no tab named {self.tab_name!r} in this spreadsheet; create it first"
        )

    def ensure_tab(self) -> None:
        """Create this client's tab if the spreadsheet doesn't have one by this name yet.

        Must run before anything that references the tab in an A1 range (_read_row,
        write, ...): a range like 'orders'!A1:B1 against a tab that doesn't exist is a 400
        from the API, not an empty result - the same wall the raw tab hit on its first
        live sync (WORKLOG, 23 Sep 2026 night), fixed there by hand in the Sheets UI.
        ensure_header() calls this first so it never needs fixing by hand again.
        """
        if any(s["properties"]["title"] == self.tab_name for s in self._all_sheets()):
            return
        body = {"requests": [{"addSheet": {"properties": {"title": self.tab_name}}}]}
        r = self.session.post(self._url(":batchUpdate"), json=body)
        _raise_for_status(r)
        self._sheet_id = int(r.json()["replies"][0]["addSheet"]["properties"]["sheetId"])

    def sheet_id(self) -> int:
        if self._sheet_id is None:
            self._sheet_id = int(self._properties()["properties"]["sheetId"])
        return self._sheet_id

    def row_count(self) -> int:
        return int(self._properties()["properties"]["gridProperties"]["rowCount"])

    def ensure_rows(self, min_rows: int) -> None:
        """Grow the tab's grid so row `min_rows` exists.

        `values.update` cannot extend the grid on its own, so this runs before any write
        that might reach past the current bottom of the sheet.
        """
        current = self.row_count()
        if current >= min_rows:
            return
        body = {"requests": [{
            "appendDimension": {
                "sheetId": self.sheet_id(),
                "dimension": "ROWS",
                "length": min_rows - current,
            }
        }]}
        r = self.session.post(self._url(":batchUpdate"), json=body)
        _raise_for_status(r)

    def write(self, start_row: int, rows: list[list[str]]) -> None:
        """Write `rows` starting at 1-indexed `start_row`, to a fixed A1 range.

        Same range every time for the same (start_row, len(rows)) - that fixed position is
        what makes a retried write idempotent rather than an append (sync.py's design).
        `valueInputOption=RAW` so nothing in a filing's text - a leading "=", a leading
        "+" - is ever interpreted as a formula (CLAUDE.md: document text is untrusted).
        """
        if not rows:
            return
        end_row = start_row + len(rows) - 1
        end_col = _col_letter(len(rows[0]))
        a1 = self._a1(f"A{start_row}:{end_col}{end_row}")
        r = self.session.put(
            self._url(f"/values/{quote(a1, safe='')}"),
            params={"valueInputOption": "RAW"},
            json={"range": a1, "majorDimension": "ROWS", "values": rows},
        )
        _raise_for_status(r)

    def _read_row(self, row: int, n_cols: int) -> list[str] | None:
        end_col = _col_letter(n_cols)
        a1 = self._a1(f"A{row}:{end_col}{row}")
        r = self.session.get(self._url(f"/values/{quote(a1, safe='')}"))
        _raise_for_status(r)
        values = r.json().get("values")
        return values[0] if values else None

    def ensure_header(self, header: list[str]) -> None:
        """Row 1 holds `header`, frozen, with a warning-only protection on the tab.

        Called on every sync run, and cheap when there is nothing to do: the write only
        happens if the stored header differs, and the freeze/protection calls are no-ops
        on Google's side if already set.
        """
        self.ensure_tab()
        if self._read_row(1, len(header)) != header:
            self.ensure_rows(1)
            self.write(1, [header])
        self._freeze_header_row()
        self._ensure_warning_only_protection()

    def _freeze_header_row(self) -> None:
        body = {"requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": self.sheet_id(),
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }]}
        r = self.session.post(self._url(":batchUpdate"), json=body)
        _raise_for_status(r)

    def _ensure_warning_only_protection(self) -> None:
        # A hard-blocking protection would stop Sravanth from filtering or annotating the
        # sheet; a warning is enough to flag "this gets overwritten by the sync".
        sheet = self._properties("protectedRanges")
        if sheet.get("protectedRanges"):
            return
        body = {"requests": [{
            "addProtectedRange": {
                "protectedRange": {
                    "range": {"sheetId": self.sheet_id()},
                    "description": "tradebot sync target - manual edits can be overwritten",
                    "warningOnly": True,
                }
            }
        }]}
        r = self.session.post(self._url(":batchUpdate"), json=body)
        _raise_for_status(r)

    def write_numbers(self, col: int, start_row: int, values: list[str]) -> None:
        """Write one column of plain decimal numbers with USER_ENTERED, so Sheets stores
        them as numbers - sortable, chartable - instead of the literal text `write()`
        always produces under RAW.

        Every value is checked against `_PLAIN_NUMBER` before any HTTP call, so filing
        text can never reach USER_ENTERED and be evaluated as a formula (CLAUDE.md:
        document text is untrusted, and the money rule - never float - is why callers
        build these strings from Decimal, not from a raw filing field). An empty string is
        the one exception: it means "leave this cell blank", not "not a number".
        """
        if not values:
            return
        for v in values:
            if v != "" and not _PLAIN_NUMBER.match(v):
                raise ValueError(f"write_numbers: not a plain number: {v!r}")
        end_row = start_row + len(values) - 1
        letter = _col_letter(col)
        a1 = self._a1(f"{letter}{start_row}:{letter}{end_row}")
        r = self.session.put(
            self._url(f"/values/{quote(a1, safe='')}"),
            params={"valueInputOption": "USER_ENTERED"},
            json={"range": a1, "majorDimension": "ROWS", "values": [[v] for v in values]},
        )
        _raise_for_status(r)

    def clear_from(self, row: int) -> None:
        """Blank every cell in every column from `row` downward.

        `clear_data()` below is `clear_from(2)`, for --rebuild. sheets/orders.py also
        calls this directly after a rewrite, to blank any row past the new end - the
        orders tab is rewritten whole each cycle (§ its own docstring), so a day that
        shrinks (a filing reclassified, in the future) must not leave a stale row behind.
        """
        a1 = self._a1(f"A{row}:Z")
        r = self.session.post(self._url(f"/values/{quote(a1, safe='')}:clear"), json={})
        _raise_for_status(r)

    def clear_data(self) -> None:
        """Blank every data row (row 2 downward), for --rebuild. The header stays."""
        self.clear_from(2)
