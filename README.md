# Dorsal PDF Extractor

Fast, deterministic PDF extraction using [`pdfium`](https://pdfium.googlesource.com/pdfium/). Get native text and bounding boxes without the overhead of heavy AI layout models. Tesseract OCR fallback for scanned pages.

## Features

* **Native Extraction:** Extracts text and its bounding boxes directly from the PDF document.
* **Tesseract OCR Fallback:** Optional optical character recognition (OCR) for scanned or empty pages.
* **Stable Block IDs:** Extracting the same file again gives the same block ids, so annotations that refer to a block keep working.
* **Schema Compliant:** Outputs records that validate against the [OATS](https://oatschema.org) `document-extraction` schema.
* **Interactive HTML Export:** Outputs can be exported to interactive HTML wireframes via the Dorsal CLI.


## Quick Start

Run the model directly against a local PDF file:

```bash
dorsal run dorsalhub/pdf-extractor ./document.pdf
```

### Configuration Options

In the CLI, you can pass options to the model using the `--opt` (or `-o`) flag.

Example: Run the extractor with OCR fallback enabled for a French language document:

```bash
dorsal run dorsalhub/pdf-extractor ./document.pdf --opt use_ocr=true --opt ocr_language=fra
```

**Options:**

* `strict` (default: `false`): Fail on a page with a zero or negative size, instead of clamping its boxes.
* `use_ocr` (default: `false`): Run Tesseract OCR on pages where no native text is found.
* `ocr_language` (default: `"eng"`): The Tesseract language code for OCR.
* `password` (no default): The password for an encrypted PDF. It isn't set in `model_config.toml`, so pass it with `--opt password=...` when you need it.

OCR needs the `ocr` extra (`pip install 'dorsal-pdf-extractor[ocr]'`, which installs `pytesseract`) and the [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html) binary on your `PATH`.

### Output Formats & Exporting

By default, the CLI outputs a validated JSON record to the current working directory.

You can export to other formats right from the CLI. For example, exporting to HTML:

```bash
dorsal run dorsalhub/pdf-extractor ./document.pdf --export=html
```

## Output

This model produces a file annotation conforming to the [OATS](https://oatschema.org) (Open Annotation Task Schemas) Document Extraction schema:

* **Schema ID:** `open/document-extraction` (v0.8.0, pinned in `model_config.toml`)
* **Key Fields:**
  * `extraction_type`: The type of extraction: `boxes`, `text` (OCR only) or `mixed`.
  * `unit`: `per_mille`. Box coordinates run from 0 to 1000 across the page, from the top-left corner.
  * `page_width` / `page_height`: The size of the pages in points, as Dorsal reports it (whole numbers for ordinary pages). A single number when every page has the same size, otherwise a list of sizes with their pages. A page whose size is reported as 0 is left out of the list.
  * `blocks`: One block per run of text that pdfium reports as a single rectangle (roughly one line), with `id`, `block_type`, `text`, `page_number` and, for native text, `box`. OCR gives one `text` block per page, with no box.
  * `attributes`: `chunk_type`, `start_page` and `end_page`. Dorsal uses these when it splits a large record into chunks.

### Block IDs

Each block's `id` is `p<page>-<hash>-<n>`, for example `p1-75690e15d48c-1`:

* `<page>` is the block's `page_number`;
* `<hash>` is the first 12 hexadecimal characters of the SHA-256 digest of the block's `text`, encoded as UTF-8;
* `<n>` counts, from 1, the blocks in the record with the same page and hash, in record order. It tells apart blocks with the same text on the same page.

The ids are unique within a record, including across the chunks Dorsal splits a large record into, and can be recomputed from the record alone. The same file, extracted with the same versions of this model, Dorsal, pypdfium2 and (for OCR) Tesseract, and the same options, always gives the same ids.

A block's id changes when its page or text changes, or when a block with the same text is added or removed before it on the same page. A change to a block's box alone, or to other blocks' text, leaves it unchanged.

## Development

### Running Tests

This repository uses `pytest` for integration testing, and `ruff` and `mypy` for linting.

```bash
uv sync --extra ocr
uv run pytest
uv run ruff check .
uv run mypy
```

The OCR test is skipped unless the Tesseract binary is installed.

## License

This project is licensed under the Apache 2.0 License.
