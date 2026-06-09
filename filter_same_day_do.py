"""Copy unmerged DOs whose date matches the current date into a `same_day` folder.

Each DO PDF carries a single date field rendered as `Date DD/MM/YYYY`
(also tolerant of `.` or `-` separators). We read that date from the
embedded text layer and, if it equals today's date, copy the file into
output/unmerged_do/same_day.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

import fitz

DATE_RE = re.compile(r"(\d{2})[\/\.\-](\d{2})[\/\.\-](\d{4})")


def extract_date(pdf_path: Path) -> dt.date | None:
    """Return the DO date as a date object, or None if not found/parseable."""
    try:
        with fitz.open(pdf_path) as doc:
            text = "".join(page.get_text("text") for page in doc[:2])
    except Exception as e:  # noqa: BLE001
        print(f"  warning: unable to read {pdf_path.name}: {e}", file=sys.stderr)
        return None

    m = DATE_RE.search(text)
    if not m:
        return None

    dd, mm, yyyy = (int(g) for g in m.groups())
    try:
        return dt.date(yyyy, mm, dd)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--do-dir",
        type=Path,
        default=Path("output/unmerged_do"),
        help="Directory containing the unmerged DO PDFs.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to match as DD/MM/YYYY (default: today's system date).",
    )
    args = parser.parse_args()

    if args.date:
        m = DATE_RE.search(args.date)
        if not m:
            print(f"ERROR: could not parse --date {args.date!r}", file=sys.stderr)
            return 1
        dd, mm, yyyy = (int(g) for g in m.groups())
        target = dt.date(yyyy, mm, dd)
    else:
        target = dt.date.today()

    if not args.do_dir.is_dir():
        print(f"ERROR: DO directory not found: {args.do_dir}", file=sys.stderr)
        return 1

    same_day_dir = args.do_dir / "same_day"
    same_day_dir.mkdir(parents=True, exist_ok=True)

    print(f"Matching DOs dated {target.strftime('%d/%m/%Y')} in {args.do_dir} ...\n")

    copied = 0
    scanned = 0
    for pdf in sorted(args.do_dir.glob("*.pdf")):
        scanned += 1
        do_date = extract_date(pdf)
        shown = do_date.strftime("%d/%m/%Y") if do_date else "no date found"

        if do_date == target:
            shutil.copy2(pdf, same_day_dir / pdf.name)
            copied += 1
            print(f"  MATCH  {pdf.name}  ({shown})  -> same_day/")
        else:
            print(f"  skip   {pdf.name}  ({shown})")

    print(f"\nScanned {scanned} DO(s); copied {copied} to {same_day_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
