# Dorsal PDF Extractor

Fast, deterministic PDF extraction using [`pdfium`](https://pdfium.googlesource.com/pdfium/). Get native text and bounding boxes without the overhead of heavy AI layout models. Tesseract OCR fallback for scanned pages.

## Features

* **Native Extraction:** Extracts text and precise spatial coordinates (bounding boxes) directly from the PDF document.
* **Tesseract OCR Fallback:** Built-in optical character recognition (OCR) fallback for scanned or empty pages (requires `pytesseract`)
* **Schema Compliant:** Outputs standardized JSON matching the `open/document-extraction` schema.
* **Interactive HTML Export:** Outputs can be exported to interactive HTML wireframes via the Dorsal CLI (requires `dorsalhub-adapters`).


## Quick Start

Run the model directly against a local PDF file:

```bash
dorsal run dorsalhub/pdf-extractor ./document.pdf

```

### Configuration Options

In the CLI, you can pass options to the model using the `--opt` (or `-o`) flag.

Example: Run the extractor with OCR fallback enabled for a French language document:

```bash
dorsal run github:dorsalhub/pdf-extractor ./document.pdf --opt use_ocr=true --opt ocr_language=fra
```

**Options:**

* `password` (default: `null`): Password for decrypted protected PDFs.
* `strict` (default: `false`): Toggle strict parsing mode for PDF processing.
* `use_ocr` (default: `false`): Enable Tesseract OCR fallback for pages where no native text tokens are detected.
* `ocr_language` (default: `"eng"`): The language code to use for the OCR fallback engine.

### Output Formats & Exporting

By default, the CLI outputs a validated JSON record to the current working directory.

You can export to other formats right from the CLI. For example, exporting to HTML:

```bash
dorsal run github:dorsalhub/pdf-extractor ./document.pdf --export=html
```

## Output

This model produces a file annotation conforming to the Open Validation Schemas Document Extraction schema:

* **Schema ID:** `open/document-extraction` (v0.5.0)
* **Key Fields:**
* `extraction_type`: Indicates the type of extraction (e.g., `boxes`, `text`, or `mixed`).
* `unit`: Geometric unit, set to `per_mille` for standardized relative spatial mapping.
* `page_width` / `page_height`: Absolute dimensions of the pages in pixels.
* `blocks`: An array of elements containing the `block_type`, `text`, `page_number`, and `box` coordinates.



## Development

### Running Tests

This repository uses `pytest` for integration testing.

```bash
pip install -e .
pytest
```

## License

This project is licensed under the Apache 2.0 License.
