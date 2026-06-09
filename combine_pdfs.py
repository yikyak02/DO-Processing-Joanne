
"""Combine each invoice with its matching delivery order into a single PDF.

Additional features:
- Copy unmerged invoices to ./output/unmerged_invoice
- Copy unmerged DOs to ./output/unmerged_do
- Rename copied files to include:
    Invoice_<number>_<company name>_DD.MM.YYYY.pdf
    DO_<number>_<company name>_DD.MM.YYYY.pdf
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import fitz

INVOICE_FILE_RE = re.compile(r"^Invoice_(\S+)\.pdf$", re.IGNORECASE)
DO_FILE_RE = re.compile(r"^DO_(\S+)\.pdf$", re.IGNORECASE)

SOLD_TO_RE = re.compile(
    r"SOLD\s*TO\s*:\s*\n.*?\n\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)

DATE_RE = re.compile(
    r"(\d{2})[\/\.-](\d{2})[\/\.-](\d{4})"
)

COLLECT_TARGETS: list[tuple[str, str]] = [
    ("sinwa", "sinwa"),
    ("francois", "francois"),
    ("fuji", "fuji"),
]


def safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:80]


def short_company_name(company: str) -> str:
    """
    Return the first word only, for example:
    RMS Marine & Offshore Service Pte Ltd -> RMS
    SDT Offshore Pte Ltd -> SDT
    Fuji Trading (Singapore) Pte Ltd -> Fuji
    """
    company = company.strip()

    if not company or company == "UnknownCompany":
        return "UnknownCompany"

    company = company.replace("_", " ")
    first = re.split(r"[\s,\(]+", company)[0]
    return safe_filename(first)


def extract_company_and_date(pdf_path: Path) -> tuple[str, str]:
    """
    Extract customer company name and date from PDF text.
    """
    company = "UnknownCompany"
    date_str = "UnknownDate"

    try:
        with fitz.open(pdf_path) as doc:
            text = ""
            for page in doc[:2]:
                text += page.get_text("text")

        sold_match = SOLD_TO_RE.search(text)
        if sold_match:
            company = safe_filename(sold_match.group(1).strip())

        date_match = DATE_RE.search(text)
        if date_match:
            dd, mm, yyyy = date_match.groups()
            date_str = f"{dd}.{mm}.{yyyy}"

    except Exception as e:
        print(f"Warning: unable to read {pdf_path}: {e}")

    return company, date_str


def index_by_number(root: Path, pattern: re.Pattern) -> dict[str, Path]:
    found: dict[str, Path] = {}

    for path in sorted(root.rglob("*.pdf")):
        m = pattern.match(path.name)
        if not m:
            continue

        num = m.group(1)

        if num in found:
            print(
                f"  note: duplicate {num} at {path} "
                f"(already have {found[num]}) — keeping first",
                file=sys.stderr,
            )
            continue

        found[num] = path

    return found


def combine(invoice_path: Path, do_path: Path, out_path: Path) -> None:
    out = fitz.open()

    with fitz.open(invoice_path) as inv:
        out.insert_pdf(inv)

    with fitz.open(do_path) as do:
        out.insert_pdf(do)

    out.save(out_path)
    out.close()


def collect_by_sold_to(combined_root: Path) -> None:
    dest_dirs = {folder: combined_root / folder for _, folder in COLLECT_TARGETS}
    counts: dict[str, int] = {folder: 0 for _, folder in COLLECT_TARGETS}

    scanned = 0

    for pdf in sorted(combined_root.glob("*.pdf")):
        scanned += 1

        with fitz.open(pdf) as doc:
            text = doc[0].get_text("text")

        m = SOLD_TO_RE.search(text)

        if not m:
            continue

        sold_to = m.group(1).strip()
        lc = sold_to.lower()

        for keyword, folder in COLLECT_TARGETS:
            if keyword in lc:
                dest_dirs[folder].mkdir(parents=True, exist_ok=True)
                shutil.copy2(pdf, dest_dirs[folder] / pdf.name)
                counts[folder] += 1
                print(f"  {pdf.name}  ->  {folder}/   ({sold_to})")

    print(f"\n  Scanned {scanned} combined PDF(s).")

    for folder, n in counts.items():
        print(f"    {folder}: {n} file(s)")


def copy_unmerged_files(
    invoices: dict[str, Path],
    dos: dict[str, Path],
    merged_numbers: set[str],
    invoice_out: Path,
    do_out: Path,
) -> None:

    invoice_out.mkdir(parents=True, exist_ok=True)
    do_out.mkdir(parents=True, exist_ok=True)

    print("\n== Copying unmerged invoices ==")

    for num, inv_path in invoices.items():
        if num in merged_numbers:
            continue

        company, date_str = extract_company_and_date(inv_path)
        company = short_company_name(company)

        new_name = f"Invoice_{num}_{company}_{date_str}.pdf"
        dest = invoice_out / new_name

        shutil.copy2(inv_path, dest)

        print(f"  copied -> {dest.name}")

    print("\n== Copying unmerged DOs ==")

    for num, do_path in dos.items():
        if num in merged_numbers:
            continue

        # DOs are usually scanned documents, so do not try to detect
        # company name or date. Keep the filename simple.
        new_name = f"DO_{num}.pdf"
        dest = do_out / new_name

        shutil.copy2(do_path, dest)

        print(f"  copied -> {dest.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--invoices",
        type=Path,
        default=Path("output/Invoice"),
        help="Directory containing split invoice PDFs.",
    )

    parser.add_argument(
        "--dos",
        type=Path,
        default=Path("output/DO"),
        help="Directory containing split DO PDFs.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/combined"),
        help="Directory to write combined PDFs into.",
    )

    args = parser.parse_args()

    if not args.invoices.exists():
        print(f"ERROR: invoice directory not found: {args.invoices}", file=sys.stderr)
        return 1

    if not args.dos.exists():
        print(f"ERROR: DO directory not found: {args.dos}", file=sys.stderr)
        return 1

    print(f"Indexing invoices under {args.invoices} ...")
    invoices = index_by_number(args.invoices, INVOICE_FILE_RE)
    print(f"  found {len(invoices)} invoice(s)")

    print(f"Indexing DOs under {args.dos} ...")
    dos = index_by_number(args.dos, DO_FILE_RE)
    print(f"  found {len(dos)} DO(s)")

    args.out.mkdir(parents=True, exist_ok=True)

    combined = 0
    merged_numbers: set[str] = set()

    for num, inv_path in invoices.items():
        do_path = dos.get(num)

        if do_path is None:
            continue

        out_path = args.out / f"{num}.pdf"

        combine(inv_path, do_path, out_path)

        print(
            f"  -> {out_path.name} "
            f"(invoice: {inv_path.name} + DO: {do_path.name})"
        )

        combined += 1
        merged_numbers.add(num)

    unused_dos = sorted(set(dos) - set(invoices))

    print(f"\nCombined {combined} invoice+DO pair(s) -> {args.out}")

    if unused_dos:
        print(
            f"DOs with no matching invoice ({len(unused_dos)}): "
            f"{', '.join(unused_dos)}",
            file=sys.stderr,
        )

    print("\n== Sorting combined PDFs by Sold To keyword ==")
    collect_by_sold_to(args.out)

    copy_unmerged_files(
        invoices,
        dos,
        merged_numbers,
        Path("output/unmerged_invoice"),
        Path("output/unmerged_do"),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
