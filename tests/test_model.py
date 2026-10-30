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

import pathlib
import tomllib
from typing import Any
from unittest.mock import MagicMock, patch

from dorsal.testing import run_model

from dorsal_pdf_extractor.model import PdfExtractor


class MockToken:
    def __init__(self, text: str, box: tuple[int, int, int, int]) -> None:
        self.text = text
        self.box = box


class MockPage:
    def __init__(self, page_number: int, width: float, height: float, tokens: list[MockToken]) -> None:
        self.page_number = page_number
        self.width = width
        self.height = height
        self.tokens = tokens


TEST_ASSETS = pathlib.Path(__file__).parent / "assets"
root = pathlib.Path(__file__).parent.parent

with open(root / "model_config.toml", "rb") as f:
    config: dict[str, Any] = tomllib.load(f)


def _run(file_path: pathlib.Path, options: dict[str, Any] | None = None, *, check_media_type: bool = False) -> Any:
    return run_model(
        annotation_model=PdfExtractor,
        file_path=str(file_path),
        schema_id=config["schema_id"],
        schema_version=config["schema_version"],
        validation_model=config.get("validation_model"),
        dependencies=config.get("dependencies") if check_media_type else None,
        options=options if options is not None else config.get("options"),
    )


def test_model_config_pins_schema_version() -> None:
    assert config["schema_version"] == "0.8.0"


def test_model_integration() -> None:
    """Runs the PDF Extractor model inside the Dorsal harness."""
    results = _run(TEST_ASSETS / "invoice_demo.pdf", check_media_type=True)
    result = results[0]

    assert result.error is None, f"Model execution failed: {result.error}"
    assert result.record is not None, "Model returned no data"
    assert result.schema_version == config["schema_version"]

    output = result.record
    assert "pdf-extractor" in output["producer"]
    assert len(output["blocks"]) > 0, "Extraction should not be empty"

    extracted_text = " ".join(block["text"] for block in output["blocks"])
    assert "ACME FakeCorp" in extracted_text
    assert "INV-9920-XQ" in extracted_text

    first_block = output["blocks"][0]
    assert first_block["block_type"] == "box"
    assert set(first_block["box"]) == {"x", "y", "width", "height"}


def test_corrupted_pdf_extraction(tmp_path: pathlib.Path) -> None:
    """Reports an error for a file that isn't a PDF."""
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_text("This is a text file pretending to be a PDF.")

    result = _run(bad_pdf)[0]

    assert result.error is not None
    assert "PDF extraction failed" in result.error


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
@patch("dorsal_pdf_extractor.model.ocr_extract_pdf_text")
def test_ocr_and_variable_dimensions(mock_ocr: MagicMock, mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Runs OCR on empty pages, and lists page sizes that differ."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [
        MockPage(1, 500, 500, [MockToken("Native text", (0, 0, 10, 10))]),
        MockPage(2, 600, 600, []),
    ]
    mock_ocr.return_value = ["", "OCR text from scanned page"]

    result = _run(dummy_pdf, {**config["options"], "use_ocr": True})[0]

    record = result.record
    assert record["extraction_type"] == "mixed"
    assert isinstance(record["page_width"], list)
    assert len(record["page_width"]) == 2
    assert record["blocks"][1]["block_type"] == "text"
    assert record["blocks"][1]["text"] == "OCR text from scanned page"


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
@patch("dorsal_pdf_extractor.model.ocr_extract_pdf_text")
def test_pure_ocr_extraction(mock_ocr: MagicMock, mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Gives a `text` extraction when only OCR finds text."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [MockPage(1, 500, 500, [])]
    mock_ocr.return_value = ["Only scanned text exists"]

    result = _run(dummy_pdf, {"use_ocr": True})[0]

    assert result.record["extraction_type"] == "text"
    assert "unit" not in result.record


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
@patch("dorsal_pdf_extractor.model.ocr_extract_pdf_text")
def test_ocr_failure_logging(mock_ocr: MagicMock, mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Still returns a record when OCR fails."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [MockPage(1, 500, 500, [])]
    mock_ocr.side_effect = Exception("Simulated Tesseract crash")

    result = _run(dummy_pdf, {"use_ocr": True})[0]

    assert result.error is None
    assert result.record["extraction_type"] == "boxes"
    assert len(result.record["blocks"]) == 0


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
def test_empty_document(mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Leaves out page sizes and attributes for a document with no pages."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = []

    result = _run(dummy_pdf)[0]

    assert result.record["extraction_type"] == "boxes"
    assert "page_width" not in result.record
    assert "page_height" not in result.record
    assert "attributes" not in result.record


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
def test_zero_page_size_is_left_out(mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Leaves out a zero page size, and lists the known sizes by page."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [
        MockPage(1, 595, 842, [MockToken("Normal", (100, 100, 200, 120))]),
        MockPage(2, 0, 0, []),
    ]

    result = _run(dummy_pdf)[0]

    assert result.error is None
    assert result.record["page_width"] == [{"value": 595, "pages": [1]}]
    assert result.record["page_height"] == [{"value": 842, "pages": [1]}]
    assert result.record["attributes"] == {"chunk_type": "page_range", "start_page": 1, "end_page": 2}


@patch("dorsal_pdf_extractor.model.extract_pdf_layout_per_mille")
def test_sub_point_page_size_is_kept(mock_layout: MagicMock, tmp_path: pathlib.Path) -> None:
    """Keeps a page size under 1 pt when Dorsal reports it."""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [MockPage(1, 0.5, 0.5, [MockToken("x", (0, 0, 1000, 1000))])]

    result = _run(dummy_pdf)[0]

    assert result.error is None
    assert result.record["page_width"] == 0.5
    assert result.record["page_height"] == 0.5
