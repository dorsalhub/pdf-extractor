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

import hashlib
import logging
import re
from importlib.metadata import version
from typing import Any

from dorsal.common.model import AnnotationModel
from dorsal.file.preprocessing.pdf import extract_pdf_layout_per_mille, ocr_extract_pdf_text

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4096
BLOCK_ID_HASH_LENGTH = 12


def block_id_prefix(page_number: int, text: str) -> str:
    """Return the part of a block id that comes from the block's page and text.

    The prefix is ``p<page_number>-<hash>``, where ``<hash>`` is the first 12
    hexadecimal characters of the SHA-256 digest of the block's UTF-8 text.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:BLOCK_ID_HASH_LENGTH]
    return f"p{page_number}-{digest}"


def assign_block_ids(blocks: list[dict[str, Any]]) -> None:
    """Give each block a deterministic id that is unique within the list.

    A block's id is ``<prefix>-<n>``, where ``<prefix>`` comes from
    :func:`block_id_prefix` and ``<n>`` counts the blocks, in list order, that
    share that prefix, starting at 1. The ids can be recomputed from a record's
    blocks alone.
    """
    seen: dict[str, int] = {}
    for block in blocks:
        prefix = block_id_prefix(block["page_number"], block["text"])
        seen[prefix] = seen.get(prefix, 0) + 1
        block["id"] = f"{prefix}-{seen[prefix]}"


class PdfExtractor(AnnotationModel):
    id = "github:dorsalhub/pdf-extractor"
    version = version("dorsal-pdf-extractor")

    _RX_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")

    @staticmethod
    def _format_dimension(dim_map: dict[int | float, list[int]], page_count: int) -> Any:
        """Format a page size map as one number, or as a list of sizes with their pages."""
        if not dim_map:
            return None
        covered = sum(len(pages) for pages in dim_map.values())
        if len(dim_map) == 1 and covered == page_count:
            return next(iter(dim_map))
        return [{"value": v, "pages": p} for v, p in dim_map.items()]

    def _build_record(
        self,
        blocks: list[dict[str, Any]],
        page_numbers: list[int],
        global_widths: dict[int | float, list[int]],
        global_heights: dict[int | float, list[int]],
    ) -> dict[str, Any]:
        """Assemble the extracted blocks and page sizes into a `document-extraction` record."""
        has_boxes = any(b.get("block_type") == "box" for b in blocks)
        has_text = any(b.get("block_type") == "text" for b in blocks)

        if has_boxes and has_text:
            extraction_type = "mixed"
        elif has_text:
            extraction_type = "text"
        else:
            extraction_type = "boxes"

        record: dict[str, Any] = {
            "extraction_type": extraction_type,
            "producer": f"pdf-extractor-v{self.version}",
            "blocks": blocks,
        }

        if extraction_type in ("boxes", "mixed"):
            record["unit"] = "per_mille"

        page_width = self._format_dimension(global_widths, len(page_numbers))
        if page_width is not None:
            record["page_width"] = page_width

        page_height = self._format_dimension(global_heights, len(page_numbers))
        if page_height is not None:
            record["page_height"] = page_height

        if page_numbers:
            record["attributes"] = {
                "chunk_type": "page_range",
                "start_page": min(page_numbers),
                "end_page": max(page_numbers),
            }

        return record

    def _clean_text(self, text: str, page_number: int) -> str:
        """Strip control characters and surrounding whitespace, and cap the length."""
        clean_text = self._RX_CONTROL_CHARS.sub("", text).strip()
        if len(clean_text) > MAX_TEXT_LENGTH:
            self.log_debug(
                "Truncating text in block on page %s (length %d > %d limit). Begins: %s",
                page_number,
                len(clean_text),
                MAX_TEXT_LENGTH,
                clean_text[:50],
            )
            clean_text = clean_text[:MAX_TEXT_LENGTH]
        return clean_text

    def main(
        self,
        password: str | None = None,
        strict: bool = False,
        use_ocr: bool = False,
        ocr_language: str = "eng",
    ) -> dict[str, Any] | None:
        """
        Dorsal model for deterministic PDF text and layout extraction.

        Args:
            password (str | None): Optional password for opening an encrypted PDF.
            strict (bool): If True, fails on a page with a zero or negative size instead of clamping its boxes.
            use_ocr (bool): If True, runs Tesseract OCR on pages with no native text.
            ocr_language (str): The Tesseract language code (e.g., 'eng').

        Returns:
            dict[str, Any] | None: A single `document-extraction` record for the whole
                document, or None on failure. Dorsal splits it into chunks if it is
                too large for the schema.
        """
        try:
            pages = extract_pdf_layout_per_mille(self.file_path, password=password, strict=strict)
        except Exception as e:
            self.set_error(f"PDF extraction failed: {e}")
            return None

        all_blocks: list[dict[str, Any]] = []
        page_numbers: list[int] = []
        global_page_widths_map: dict[int | float, list[int]] = {}
        global_page_heights_map: dict[int | float, list[int]] = {}
        empty_pages: list[int] = []

        for page in pages:
            page_numbers.append(page.page_number)
            if page.width > 0:
                global_page_widths_map.setdefault(page.width, []).append(page.page_number)
            if page.height > 0:
                global_page_heights_map.setdefault(page.height, []).append(page.page_number)

            if not page.tokens:
                empty_pages.append(page.page_number)
                continue

            for token in page.tokens:
                clean_text = self._clean_text(token.text, page.page_number)
                if not clean_text:
                    continue

                x0, y0, x1, y1 = token.box
                all_blocks.append(
                    {
                        "id": "",
                        "block_type": "box",
                        "text": clean_text,
                        "page_number": page.page_number,
                        "box": {
                            "x": x0,
                            "y": y0,
                            "width": max(0, x1 - x0),
                            "height": max(0, y1 - y0),
                        },
                    }
                )

        if use_ocr and empty_pages:
            self.log_debug("Running fallback OCR on %d empty pages...", len(empty_pages))
            try:
                ocr_results = ocr_extract_pdf_text(self.file_path, language=ocr_language, password=password)

                for page_num in empty_pages:
                    ocr_index = page_num - 1
                    if ocr_index < len(ocr_results):
                        text = self._clean_text(ocr_results[ocr_index], page_num)
                        if text:
                            all_blocks.append(
                                {
                                    "id": "",
                                    "block_type": "text",
                                    "text": text,
                                    "page_number": page_num,
                                }
                            )
            except Exception as e:
                self.log_warning("Fallback OCR failed: %s", e)

        all_blocks.sort(key=lambda x: x["page_number"])
        assign_block_ids(all_blocks)

        return self._build_record(all_blocks, page_numbers, global_page_widths_map, global_page_heights_map)
