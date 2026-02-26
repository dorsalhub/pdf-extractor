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
from unittest.mock import patch
import tomllib

import pytest
from dorsal.testing import run_model

from pdf_extractor.model import PdfExtractor

class MockToken:
    def __init__(self, text, box):
        self.text = text
        self.box = box

class MockPage:
    def __init__(self, page_number, width, height, tokens):
        self.page_number = page_number
        self.width = width
        self.height = height
        self.tokens = tokens

TEST_ASSETS = pathlib.Path(__file__).parent / "assets"
root = pathlib.Path(__file__).parent.parent

with open(root / "model_config.toml", "rb") as f:
    config = tomllib.load(f)

def test_model_integration():
    """Tests the PDF Extractor model running inside the Dorsal harness."""
    pdf_file = TEST_ASSETS / "invoice_demo.pdf"

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(pdf_file),
        schema_id=config["schema_id"],
        validation_model=config.get("validation_model"),
        dependencies=config.get("dependencies"),
        options=config.get("options"),
    )

    # Basic execution assertions
    assert result.error is None, f"Model execution failed: {result.error}"
    assert result.record is not None, "Model returned no data"

    output = result.record

    # Schema & structure assertions
    assert "pdf-extractor" in output["producer"]
    assert "blocks" in output
    assert len(output["blocks"]) > 0, "Extraction should not be empty"
    
    # Verify specific content from the simple_invoice_demo.pdf
    extracted_text = " ".join([block["text"] for block in output["blocks"] if block.get("text")])
    assert "ACME FakeCorp" in extracted_text
    assert "INV-9920-XQ" in extracted_text
    
    # Verify bounding box structure exists
    first_block = output["blocks"][0]
    if first_block["block_type"] == "box":
        assert "box" in first_block
        assert "x" in first_block["box"]
        assert "width" in first_block["box"]


def test_corrupted_pdf_extraction(tmp_path):
    """Hits the main except block: `except Exception as e: self.set_error(...)`"""
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_text("This is a text file pretending to be a PDF.")

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(bad_pdf),
        schema_id=config["schema_id"],
        validation_model=config.get("validation_model"),
        options=config.get("options")
    )

    assert result.error is not None
    assert "PDF extraction failed" in result.error


@patch('pdf_extractor.model.extract_pdf_layout_per_mille')
@patch('pdf_extractor.model.ocr_extract_pdf_text')
def test_ocr_and_variable_dimensions(mock_ocr, mock_layout, tmp_path):
    """
    Hits: 
    - `if not page.tokens: empty_pages.append(...)`
    - `if use_ocr and empty_pages:`
    - variable dimensions list comprehension
    - `extraction_type = "mixed"`
    """
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    # Page 1: 500x500 (has tokens)
    # Page 2: 600x600 (empty, triggers OCR)
    mock_layout.return_value = [
        MockPage(1, 500, 500, [MockToken("Native text", (0, 0, 10, 10))]),
        MockPage(2, 600, 600, [])
    ]
    mock_ocr.return_value = ["", "OCR text from scanned page"]

    test_options = config.get("options", {}).copy()
    test_options["use_ocr"] = True

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(dummy_pdf),
        schema_id=config["schema_id"],
        options=test_options
    )

    record = result.record
    assert record["extraction_type"] == "mixed"
    assert isinstance(record["page_width"], list)
    assert len(record["page_width"]) == 2
    assert record["blocks"][1]["block_type"] == "text"
    assert record["blocks"][1]["text"] == "OCR text from scanned page"


@patch('pdf_extractor.model.extract_pdf_layout_per_mille')
@patch('pdf_extractor.model.ocr_extract_pdf_text')
def test_pure_ocr_extraction(mock_ocr, mock_layout, tmp_path):
    """Hits `elif has_text: extraction_type = "text"`"""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [MockPage(1, 500, 500, [])]
    mock_ocr.return_value = ["Only scanned text exists"]

    test_options = {"use_ocr": True}

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(dummy_pdf),
        schema_id=config["schema_id"],
        options=test_options
    )

    assert result.record["extraction_type"] == "text"


@patch('pdf_extractor.model.extract_pdf_layout_per_mille')
@patch('pdf_extractor.model.ocr_extract_pdf_text')
def test_ocr_failure_logging(mock_ocr, mock_layout, tmp_path):
    """Hits `except Exception as e: logger.warning(f"Fallback OCR failed: {e}")`"""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    mock_layout.return_value = [MockPage(1, 500, 500, [])]
    mock_ocr.side_effect = Exception("Simulated Tesseract crash")

    test_options = {"use_ocr": True}

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(dummy_pdf),
        schema_id=config["schema_id"],
        options=test_options
    )

    # Extraction succeeds, but falls back to empty boxes due to OCR crash
    assert result.error is None
    assert result.record["extraction_type"] == "boxes"
    assert len(result.record["blocks"]) == 0


@patch('pdf_extractor.model.extract_pdf_layout_per_mille')
def test_empty_document(mock_layout, tmp_path):
    """
    Hits:
    - `if not dim_map: return None`
    - `else: extraction_type = "boxes"`
    """
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.touch()

    # Simulate a PDF with 0 pages
    mock_layout.return_value = []

    result = run_model(
        annotation_model=PdfExtractor,
        file_path=str(dummy_pdf),
        schema_id=config["schema_id"]
    )

    assert result.record["extraction_type"] == "boxes"
    assert "page_width" not in result.record
    assert "page_height" not in result.record
