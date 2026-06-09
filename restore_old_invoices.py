"""Copy OLD invoice versions back into the Unmerge Invoice folder by invoice number.

For every invoice PDF directly inside the Unmerge Invoice folder we read its
invoice number (the digits in a name like ``Invoice_02611205_Century_...pdf``).
If the ``OLD`` subfolder contains a file with the same invoice number, that OLD
file is copied up into the parent folder.

Matching is by invoice number only — the OLD copy usually carries extra
handwritten notes in its filename (e.g. "RE-SIGN 05.06"), so the names differ.
We keep both: the OLD file is copied in alongside the parent's original rather
than replacing it. When the OLD filename is identical to one already present,
the copy simply refreshes that file.

Runs as a dry-run by default — pass ``--apply`` to actually copy.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Same NAS folder, addressed differently per OS. On macOS the share mounts at
# /Volumes/AMO-NAS; on Windows that share is mapped to the Z: drive.
if sys.platform == "win32":
    DEFAULT_DIR = Path(r"Z:\ADMIN\11. eInvoicing\0.2 Unmerge Invoice")
else:
    DEFAULT_DIR = Path("/Volumes/AMO-NAS/ADMIN/11. eInvoicing/0.2 Unmerge Invoice")
OLD_SUBDIR = "OLD"

INVOICE_NUM_RE = re.compile(r"Invoice[_\s-]*(\d+)", re.IGNORECASE)


def invoice_number(path: Path) -> str | None:
    """Return the invoice number embedded in the filename, or None."""
    m = INVOICE_NUM_RE.search(path.name)
    return m.group(1) if m else None


def index_by_number(pdfs: list[Path]) -> dict[str, list[Path]]:
    """Group PDFs by their invoice number (files without one are skipped)."""
    by_num: dict[str, list[Path]] = {}
    for p in pdfs:
        num = invoice_number(p)
        if num:
            by_num.setdefault(num, []).append(p)
    return by_num


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help="Unmerge Invoice folder containing the invoices and the OLD subfolder.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually copy the files. Without this flag the script only previews.",
    )
    args = parser.parse_args()

    parent = args.dir
    old_dir = parent / OLD_SUBDIR

    if not parent.is_dir():
        print(
            f"ERROR: folder not found: {parent}\n"
            "Is the NAS mounted? Connect to it (Finder -> Cmd+K -> smb://...) and retry.",
            file=sys.stderr,
        )
        return 1
    if not old_dir.is_dir():
        print(f"ERROR: OLD subfolder not found: {old_dir}", file=sys.stderr)
        return 1

    parent_pdfs = sorted(parent.glob("*.pdf"))  # top level only, not OLD/
    old_pdfs = sorted(old_dir.glob("*.pdf"))

    old_by_num = index_by_number(old_pdfs)
    parent_by_num = index_by_number(parent_pdfs)

    mode = "APPLY" if args.apply else "DRY-RUN (no files changed; pass --apply to copy)"
    print(f"== {mode} ==")
    print(f"Parent: {parent}")
    print(f"OLD:    {old_dir}")
    print(f"  {len(parent_pdfs)} invoice(s) in parent, {len(old_pdfs)} in OLD.\n")

    copied = refreshed = 0
    matched_numbers = sorted(set(parent_by_num) & set(old_by_num))

    if not matched_numbers:
        print("No invoice numbers in the parent folder also appear in OLD.")
        return 0

    for num in matched_numbers:
        for old_file in old_by_num[num]:
            dest = parent / old_file.name
            already_here = dest.exists()
            tag = "refresh" if already_here else "copy   "
            print(f"  [{tag}] {num}: OLD/{old_file.name}  ->  parent/")
            if args.apply:
                shutil.copy2(old_file, dest)
            if already_here:
                refreshed += 1
            else:
                copied += 1

    verb = "Copied" if args.apply else "Would copy"
    print(
        f"\n{verb} {copied} new + {refreshed} refreshed file(s) "
        f"for {len(matched_numbers)} matched invoice number(s)."
    )
    if not args.apply:
        print("Re-run with --apply to perform the copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
