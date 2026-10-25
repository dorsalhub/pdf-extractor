# Copyright 2026 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run the model on real PDFs and check every record against the pinned OATS schema."""

import hashlib
import importlib.util
import pathlib
import shutil
import tomllib
from typing import Any
from unittest.mock import MagicMock, patch

import oatschema
import pytest
from dorsal.testing import run_model
from pdf_factory import A4, A5_LANDSCAPE, LETTER, Page, build_pdf

from dorsal_pdf_extractor.model import PdfExtractor

ROOT = pathlib.Path(__file__).parent.parent
ASSETS = pathlib.Path(__file__).parent / "assets"

with open(ROOT / "model_config.toml", "rb") as f:
    CONFIG: dict[str, Any] = tomllib.load(f)

SCHEMA_NAME = CONFIG["schema_id"].removeprefix("open/")
SCHEMA_VERSION = CONFIG["schema_version"]

GENERATED: dict[str, list[Page]] = {
    "two_lines": [Page(A4, [(72, 770, "The quick brown fox"), (72, 740, "Total (EUR): 100")])],
    "mixed_page_sizes": [
        Page(A4, [(72, 770, "A4 page")]),
        Page(LETTER, [(72, 700, "Letter page")]),
        Page(A5_LANDSCAPE, [(50, 300, "A5 landscape page")]),
    ],
    "blank_page": [Page(A4, [])],
    "repeated_text": [
        Page(A4, [(72, 770, "Same"), (72, 740, "Same"), (72, 710, "Other"), (72, 680, "Same")]),
        Page(A4, [(72, 770, "Same")]),
    ],
    "zero_media_box": [Page((0, 0, 0, 0), [(72, 700, "Zero MediaBox")])],
    "sub_point_page": [Page((0, 0, 0.5, 0.5), [(0, 0, "x")])],
    "sub_point_page_after_normal_page": [Page(A4, [(72, 770, "Normal page")]), Page((0, 0, 0.5, 0.5), [])],
}


def _pdf_path(case: str, tmp_path: pathlib.Path) -> pathlib.Path:
    if case == "invoice_demo":
        return ASSETS / "invoice_demo.pdf"
    path = tmp_path / f"{case}.pdf"
    path.write_bytes(build_pdf(GENERATED[case]))
    return path


def _run(path: pathlib.Path, options: dict[str, Any] | None = None, *, check_media_type: bool = True) -> list[Any]:
    return run_model(
        annotation_model=PdfExtractor,
        file_path=str(path),
        schema_id=CONFIG["schema_id"],
        schema_version=SCHEMA_VERSION,
        dependencies=CONFIG.get("dependencies") if check_media_type else None,
        options={**CONFIG["options"], **(options or {})},
    )


def _records(results: list[Any]) -> list[dict[str, Any]]:
    records = []
    for result in results:
        assert result.error is None, result.error
        assert result.schema_version == SCHEMA_VERSION
        records.extend(result.records)
    return records


def _assert_valid(record: dict[str, Any]) -> None:
    errors = [str(e) for e in oatschema.iter_errors(record, SCHEMA_NAME, SCHEMA_VERSION)]
    assert errors == []


def _expected_ids(blocks: list[dict[str, Any]]) -> list[str]:
    counts: dict[tuple[int, str], int] = {}
    ids = []
    for block in blocks:
        key = (block["page_number"], block["text"])
        counts[key] = counts.get(key, 0) + 1
        digest = hashlib.sha256(block["text"].encode("utf-8")).hexdigest()[:12]
        ids.append(f"p{block['page_number']}-{digest}-{counts[key]}")
    return ids


CASES = ["invoice_demo", *GENERATED]


@pytest.mark.parametrize("case", CASES)
def test_records_are_valid_at_pinned_version(case: str, tmp_path: pathlib.Path) -> None:
    records = _records(_run(_pdf_path(case, tmp_path)))
    assert records
    for record in records:
        _assert_valid(record)


@pytest.mark.parametrize("case", CASES)
def test_block_ids_follow_the_documented_scheme(case: str, tmp_path: pathlib.Path) -> None:
    blocks = [b for r in _records(_run(_pdf_path(case, tmp_path))) for b in r["blocks"]]
    ids = [b["id"] for b in blocks]
    assert ids == _expected_ids(blocks)
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", CASES)
def test_two_runs_give_the_same_record(case: str, tmp_path: pathlib.Path) -> None:
    path = _pdf_path(case, tmp_path)
    assert _records(_run(path)) == _records(_run(path))


def test_repeated_text_gets_numbered_ids(tmp_path: pathlib.Path) -> None:
    blocks = _records(_run(_pdf_path("repeated_text", tmp_path)))[0]["blocks"]
    same = hashlib.sha256(b"Same").hexdigest()[:12]
    other = hashlib.sha256(b"Other").hexdigest()[:12]
    assert [b["id"] for b in blocks] == [
        f"p1-{same}-1",
        f"p1-{same}-2",
        f"p1-{other}-1",
        f"p1-{same}-3",
        f"p2-{same}-1",
    ]


def test_invoice_block_id(tmp_path: pathlib.Path) -> None:
    first = _records(_run(_pdf_path("invoice_demo", tmp_path)))[0]["blocks"][0]
    assert first["text"] == "INVOICE"
    assert first["id"] == "p1-" + hashlib.sha256(b"INVOICE").hexdigest()[:12] + "-1"


class _Token:
    def __init__(self, text: str, box: tuple[int, int, int, int]) -> None:
        self.text = text
        self.box = box


class _Page:
    def __init__(self, page_number: int, tokens: list[_Token]) -> None:
        self.page_number = page_number
        self.width = 595
        self.height = 842
        self.tokens = tokens


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
def test_ids_are_unique_across_chunks(mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    dummy_pdf = tmp_path / "large.pdf"
    dummy_pdf.touch()
    per_page = 60_000
    mock_layout.return_value = [
        _Page(page, [_Token(f"line {i % 1000}", (10, 10, 20, 20)) for i in range(per_page)]) for page in (1, 2)
    ]

    records = _records(_run(dummy_pdf, check_media_type=False))

    assert len(records) == 2
    ids = [b["id"] for r in records for b in r["blocks"]]
    assert len(ids) == 2 * per_page
    assert len(set(ids)) == len(ids)
    validator = oatschema.get_validator(SCHEMA_NAME, SCHEMA_VERSION)
    for record in records:
        assert validator.is_valid(record)


def _ocr_available() -> bool:
    return (
        importlib.util.find_spec("pytesseract") is not None
        and importlib.util.find_spec("PIL") is not None
        and shutil.which("tesseract") is not None
    )


@pytest.mark.skipif(not _ocr_available(), reason="needs pytesseract, Pillow and the tesseract binary")
def test_scanned_pdf_with_ocr_is_valid_and_stable(tmp_path: pathlib.Path) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(ASSETS / "invoice_demo.pdf"))
    image = pdf[0].render(scale=2).to_pil().convert("RGB")
    pdf.close()
    scanned = tmp_path / "scanned.pdf"
    image.save(scanned, "PDF", resolution=144)

    without_ocr = _records(_run(scanned))
    assert without_ocr[0]["blocks"] == []

    first = _records(_run(scanned, {"use_ocr": True}))
    second = _records(_run(scanned, {"use_ocr": True}))
    assert first == second
    blocks = first[0]["blocks"]
    assert [b["block_type"] for b in blocks] == ["text"]
    assert "INVOICE" in blocks[0]["text"]
    assert [b["id"] for b in blocks] == _expected_ids(blocks)
    for record in first:
        _assert_valid(record)
