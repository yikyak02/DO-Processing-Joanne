"""Sort customer invoices by Sold To, then merge with matching PO Excel/PDF files."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz

SOLD_TO_RE = re.compile(
    r"SOLD\s*TO\s*:\s*\n\s*DELIVER\s*TO\s*:\s*\n\s*(.+)",
    re.IGNORECASE,
)
PO_NUMBER_RE = re.compile(r"PO\s*NUMBER\s*\n\s*(\S+)", re.IGNORECASE)
DATE_RE = re.compile(r"Date\s+(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

INVOICE_FILE_RE = re.compile(r"^Invoice_(\S+)\.pdf$", re.IGNORECASE)
DO_FILE_RE = re.compile(r"^DO_(\S+)\.pdf$", re.IGNORECASE)

TARGETS = [
    ("Con-Lash Supplies", ["con-lash supplies", "con lash supplies"]),
]


def read_page1_text(pdf_path: Path) -> str:
    with fitz.open(pdf_path) as doc:
        return doc[0].get_text("text")


def extract_sold_to(text: str):
    m = SOLD_TO_RE.search(text)
    return m.group(1).strip() if m else None


def extract_po_number(text: str):
    m = PO_NUMBER_RE.search(text)
    return m.group(1).strip() if m else None


def extract_date_ddmmyyyy(text: str):
    m = DATE_RE.search(text)
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None


def target_folder(company: str):
    lc = company.lower()
    for folder, keywords in TARGETS:
        if any(kw in lc for kw in keywords):
            return folder
    return None


def sort_invoices(invoices_root: Path, po_root: Path):
    po_root.mkdir(parents=True, exist_ok=True)

    for pdf in sorted(invoices_root.rglob("Invoice_*.pdf")):
        company = extract_sold_to(read_page1_text(pdf))

        if not company:
            continue

        folder = target_folder(company)

        if folder is None:
            continue

        dest_dir = po_root / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(pdf, dest_dir / pdf.name)

        print(f"{pdf.name} -> PO/{folder}/")


def find_po_data_folder(customer_folder_name: str, po_data_root: Path):
    if not po_data_root.exists():
        return None

    lc = customer_folder_name.lower()

    for sub in po_data_root.iterdir():
        if sub.is_dir() and sub.name.lower() in lc:
            return sub

    return None


def find_po_xls(po_folder: Path, po_number: str):
    """Find matching PO file (Excel OR PDF)."""

    po_number_lc = po_number.lower()

    for p in po_folder.iterdir():
        if not p.is_file():
            continue

        name_lc = p.name.lower()

        if po_number_lc not in name_lc:
            continue

        if p.suffix.lower() in [".xls", ".xlsx", ".pdf"]:
            return p

    return None


def find_soffice(explicit: Path | None = None):
    if explicit:
        if explicit.exists():
            return str(explicit)
        return None

    which = shutil.which("soffice")

    if which:
        return which

    possible = [
        Path(r"C:/Program Files/LibreOffice/program/soffice.exe"),
        Path(r"C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ]

    for p in possible:
        if p.exists():
            return str(p)

    return None


def xls_to_pdf(xls_path: Path, out_dir: Path, soffice_exec: str):
    out_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            soffice_exec,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(xls_path),
        ],
        check=True,
    )

    pdf = out_dir / (xls_path.stem + ".pdf")

    if not pdf.exists():
        raise RuntimeError(f"PDF not created for {xls_path}")

    return pdf


def is_blank_pdf_page(page, text_min_chars: int = 3, dark_pixel_ratio_limit: float = 0.001) -> bool:
    """Return True if a PDF page is visually blank.

    Some LibreOffice Excel-to-PDF blank pages still contain invisible/white images,
    so checking text or image count alone is not enough. This function renders the
    page in grayscale and checks whether almost all pixels are white.
    """
    text = page.get_text("text").strip()

    if len(text) >= text_min_chars:
        return False

    pix = page.get_pixmap(
        matrix=fitz.Matrix(0.5, 0.5),
        colorspace=fitz.csGRAY,
        alpha=False,
    )

    data = pix.samples
    total_pixels = len(data)

    if total_pixels == 0:
        return True

    # Count pixels that are not close to white.
    dark_pixels = sum(1 for pixel in data if pixel < 245)
    dark_ratio = dark_pixels / total_pixels

    return dark_ratio <= dark_pixel_ratio_limit


def remove_blank_pages(pdf_path: Path) -> None:
    """Remove visually blank pages from a PDF.

    This is mainly used for Fuji PO PDFs converted from Excel by LibreOffice.
    It removes pages that look blank even if LibreOffice inserted white images.
    """
    cleaned_path = None

    with fitz.open(pdf_path) as doc:
        blank_pages = []

        for page_index in range(len(doc)):
            if is_blank_pdf_page(doc[page_index]):
                blank_pages.append(page_index)

        if not blank_pages:
            return

        for page_index in reversed(blank_pages):
            doc.delete_page(page_index)

        cleaned_path = pdf_path.with_name(pdf_path.stem + "_cleaned.pdf")
        doc.save(cleaned_path)

    if cleaned_path and cleaned_path.exists():
        cleaned_path.replace(pdf_path)


def combine_pdfs(parts, out_path):
    out = fitz.open()

    for part in parts:
        with fitz.open(part) as src:
            out.insert_pdf(src)

    out.save(out_path)
    out.close()


def index_dos(do_root: Path):
    found = {}

    if not do_root.exists():
        return found

    for path in sorted(do_root.rglob("*.pdf")):
        m = DO_FILE_RE.match(path.name)

        if not m:
            continue

        found.setdefault(m.group(1), path)

    return found


def invoice_number_from_filename(invoice_pdf: Path):
    m = INVOICE_FILE_RE.match(invoice_pdf.name)

    return m.group(1) if m else None


def merge_invoices_with_pos(
    po_root: Path,
    po_data_root: Path,
    do_root: Path,
    soffice_path: Path | None = None,
):
    soffice_exec = find_soffice(soffice_path)

    if not soffice_exec:
        print("ERROR: soffice not found")
        return

    do_index = index_dos(do_root)

    for customer_dir in sorted(p for p in po_root.iterdir() if p.is_dir()):
        data_folder = find_po_data_folder(customer_dir.name, po_data_root)

        if data_folder is None:
            continue

        combined_dir = customer_dir / "combined"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            for invoice_pdf in sorted(customer_dir.glob("Invoice_*.pdf")):
                page1_text = read_page1_text(invoice_pdf)

                po_num = extract_po_number(page1_text)

                if not po_num:
                    continue

                xls = find_po_xls(data_folder, po_num)

                if xls is None:
                    print(f"{invoice_pdf.name}: PO {po_num} not found")
                    continue

                if xls.suffix.lower() == ".pdf":
                    po_pdf = xls
                else:
                    po_pdf = xls_to_pdf(xls, tmp_dir, soffice_exec)
                    remove_blank_pages(po_pdf)

                parts = [invoice_pdf, po_pdf]

                inv_num = invoice_number_from_filename(invoice_pdf)

                do_pdf = do_index.get(inv_num) if inv_num else None

                # Only save combined documents when Invoice + PO + DO are all available.
                # If DO is missing, skip this invoice and do not create a combined file.
                if not do_pdf:
                    print(f"{invoice_pdf.name}: DO not found, skipped")
                    continue

                parts.append(do_pdf)

                if customer_dir.name == "Con-Lash Supplies":
                    date_str = extract_date_ddmmyyyy(page1_text)

                    if date_str and inv_num:
                        out_name = f"{po_num}_{inv_num}_{date_str}.pdf"
                    else:
                        out_name = invoice_pdf.name
                else:
                    out_name = f"{inv_num}.pdf" if inv_num else invoice_pdf.name

                combined_dir.mkdir(parents=True, exist_ok=True)

                out_path = combined_dir / out_name

                combine_pdfs(parts, out_path)

                print(f"Merged -> {out_path}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--invoices",
        type=Path,
        default=Path("output/Invoice"),
    )

    parser.add_argument(
        "--po-out",
        type=Path,
        default=Path("output/PO"),
    )

    parser.add_argument(
        "--po-data",
        type=Path,
        default=Path("data/PO"),
    )

    parser.add_argument(
        "--dos",
        type=Path,
        default=Path("output/DO"),
    )

    parser.add_argument(
        "--soffice",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    print("== Phase 1 ==")
    sort_invoices(args.invoices, args.po_out)

    print("== Phase 2 ==")
    merge_invoices_with_pos(
        args.po_out,
        args.po_data,
        args.dos,
        args.soffice,
    )


if __name__ == "__main__":
    raise SystemExit(main())
