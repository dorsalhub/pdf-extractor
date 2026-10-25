# Changelog

## 0.6.0

### Changed

- **Records are validated and stamped as OATS `document-extraction` 0.8.0.** `model_config.toml` now pins `schema_version = "0.8.0"`. Before, Dorsal used its default, 0.5.0. The record's fields and shape are the same.
- **Block ids are deterministic.** Each `id` is `p<page>-<hash>-<n>`: the page number, the first 12 hexadecimal characters of the SHA-256 digest of the block's text, and a count, from 1, of blocks with the same page and hash. Extracting the same file again gives the same ids. Before, every block got a random UUID4 on every run. See the README's "Block IDs" section.
- **Requires `dorsalhub>=0.12.1,<0.13`.** The model uses Dorsal's internal PDF functions, so the range has an upper bound. Dorsal 0.12.1 fixes boxes on rotated, cropped and offset pages, and the size of pages under 1 pt.
- OCR text has control characters removed, as native text already did.

### Fixed

- A page whose size Dorsal reports as 0 no longer makes the record invalid. Its size is left out of `page_width` and `page_height`, which then list the other pages' sizes by page. Before, Dorsal dropped the whole annotation.
- `attributes.start_page` and `attributes.end_page` cover every page, including pages left out of `page_width` and `page_height`.

### Added

- An `ocr` extra that installs `pytesseract`. OCR also needs the Tesseract binary.
- A contract test that runs the model on real PDFs and validates every record with `oatschema` at the pinned version, and tests that ids are stable and unique.
- `ruff` and `mypy` configuration.
- Package licence metadata (`Apache-2.0`) and the repository URL.

### Removed

- The unused `dorsalhub-adapters` development dependency.
