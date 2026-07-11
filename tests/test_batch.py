"""Tests for OCR fallback, confidence scoring, and the batch runner."""

import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genetic_report_extractor.extractor import extract_from_pdf  # noqa: E402
from genetic_report_extractor.confidence import score_report  # noqa: E402
from genetic_report_extractor.pdf import extract_document, NoTextLayer, ocr_available  # noqa: E402
from genetic_report_extractor import batch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(os.path.dirname(HERE), "examples")


def _make_scanned(src_pdf: str, out_pdf: str) -> None:
    """Rasterise a PDF into an image-only (text-less) PDF."""
    src = fitz.open(src_pdf)
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, pixmap=pix)
    out.save(out_pdf)


def test_confidence_high_on_good_reports():
    for r in extract_from_pdf(os.path.join(EX, "report3_1933708.pdf")):
        s = score_report(r)
        assert s["level"] == "high"
        assert not s["needs_review"]
        assert s["missing"] == []


def test_scan_detection_and_ocr(tmp_path):
    scan = str(tmp_path / "scan.pdf")
    _make_scanned(os.path.join(EX, "report2_1223557.pdf"), scan)

    # Without OCR it is correctly flagged as a scan.
    try:
        extract_document(scan)
        assert False, "expected NoTextLayer"
    except NoTextLayer:
        pass

    if not ocr_available():
        return  # environment without tesseract — detection already verified
    reports = extract_from_pdf(scan, ocr=True)
    assert reports and reports[0].patient.patient_no == "1223557"
    assert reports[0].ocr_used is True
    assert "ocr" in score_report(reports[0])["flags"]


def test_batch_run_resume_and_export(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "a").mkdir(parents=True)
    import shutil
    shutil.copy(os.path.join(EX, "report1_1150124_couple.pdf"), corpus / "a" / "c.pdf")
    shutil.copy(os.path.join(EX, "report2_1223557.pdf"), corpus / "a" / "s.pdf")
    (corpus / "a" / "broken.pdf").write_text("not a pdf")

    db = str(tmp_path / "batch.db")
    stats = batch.run_batch(str(corpus), db, workers=2, ocr=False,
                            quarantine=str(tmp_path / "q"))
    assert stats["files_total"] == 3
    assert stats["files_success"] == 2      # couple + single
    assert stats["files_error"] == 1        # broken
    assert stats["records"] == 3            # 2 (couple split) + 1
    assert os.path.exists(tmp_path / "q" / "broken.pdf")

    # Resume: nothing new to do.
    again = batch.run_batch(str(corpus), db, workers=2, ocr=False)
    assert again["records"] == 3

    # Exports
    csv_path = str(tmp_path / "out.csv")
    n = batch.export_csv(db, csv_path)
    assert n == 3
    import csv as _csv
    header = next(_csv.reader(open(csv_path)))
    assert header.count("needs_review") == 1        # no duplicate meta columns
    assert "source_file" in header and "confidence" in header

    xlsx_path = str(tmp_path / "out.xlsx")
    assert batch.export_xlsx(db, xlsx_path) == 3
    assert os.path.getsize(xlsx_path) > 0

    err = batch.export_errors(db, str(tmp_path / "err.csv"))
    assert err == 1


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    import pathlib
                    fn(pathlib.Path(d))
            else:
                fn()
            print(f"PASS {name}")
    print("All batch tests passed.")
