"""Which ISINs belong to the same company.

An Indian ISIN is IN + issuer type (E for a company) + a four-character issuer code +
security type (01 for equity shares, 07 for bonds, ...) + a two-character serial + a check
digit. The first seven characters, `INE019A`, identify the company; the serial changes when
the depository reissues the ISIN, which it does after a face-value split.

That matters because NSE's announcements API tags every filing with the company's
*original* equity ISIN, while the bhavcopy carries the *current* one (found 27 Sep 2026:
JSWSTEEL files as INE019A01020 and trades as INE019A01038). Comparing whole ISINs made 85
of the first 495 backfill companies look filing-free. So any join between announcements
and market data compares issuer codes, never whole ISINs. SQL writes the same rule as
`left(isin, 7)`.

A same-issuer bond ISIN (HUDCO's INE031A07873) counts as the same company too: the filing
is still that company's, and its category, not its ISIN, decides whether it matters.
"""

ISSUER_CODE_LENGTH = 7


def issuer_code(isin: str) -> str:
    return isin.strip()[:ISSUER_CODE_LENGTH]


def same_issuer(a: str, b: str) -> bool:
    return issuer_code(a) == issuer_code(b)
