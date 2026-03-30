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

import uuid
import logging
from typing import Any
from importlib.metadata import version
from dorsal.common.model import AnnotationModel
from dorsal.file.preprocessing.pdf import extract_pdf_layout_per_mille, ocr_extract_pdf_text

logger = logging.getLogger(__name__)

class PdfExtractor(AnnotationModel):
    id = "github:dorsalhub/pdf-extractor"
    version = version("dorsal-pdf-extractor")

    def _format_dimension(self, dim_map: dict[int | float, list[int]]) -> Any:
        """Formats page width/height maps into the schema's expected structure."""
        if not dim_map:
            return None
        if len(dim_map) == 1:
            return list(dim_map.keys())[0]
        return [{"value": v, "pages": p} for v, p in dim_map.items()]

    def _build_record(
        self, 
        blocks: list[dict[str, Any]], 
        global_widths: dict[int | float, list[int]], 
        global_heights: dict[int | float, list[int]]
    ) -> dict[str, Any]:
        """
        Dorsal model for deterministic PDF text and layout extraction.

        Extracts text and spatial coordinates (bounding boxes) using pdfium, with optional Tesseract OCR fallback for scanned pages.
        Chunks massive documents into safe, schema-compliant `open/document-extraction`-valid records.

        """
        pages_in_chunk = set()
        has_boxes = False
        has_text = False

        for b in blocks:
            page_num = b.get("page_number")
            if page_num is not None:
                pages_in_chunk.add(page_num)
                
            b_type = b.get("block_type")
            if b_type == "box":
                has_boxes = True
            elif b_type == "text":
                has_text = True

        start_page = min(pages_in_chunk) if pages_in_chunk else None
        end_page = max(pages_in_chunk) if pages_in_chunk else None

        chunk_widths = {}
        chunk_heights = {}
        
        if not blocks:
            chunk_widths = global_widths
            chunk_heights = global_heights
            
            all_pages = [p for p_list in global_widths.values() for p in p_list]
            if all_pages:
                start_page = min(all_pages)
                end_page = max(all_pages)
        elif start_page is not None:
            for w_val, p_list in global_widths.items():
                intersect = [p for p in p_list if p in pages_in_chunk]
                if intersect:
                    chunk_widths[w_val] = intersect

            for h_val, p_list in global_heights.items():
                intersect = [p for p in p_list if p in pages_in_chunk]
                if intersect:
                    chunk_heights[h_val] = intersect

        if has_boxes and has_text:
            extraction_type = "mixed"
        elif has_boxes:
            extraction_type = "boxes"
        elif has_text:
            extraction_type = "text"
        else:
            extraction_type = "boxes" 

        record: dict[str, Any] = {
            "extraction_type": extraction_type,
            "producer": f"pdf-extractor-v{self.version}",
            "blocks": blocks,
        }
        
        if start_page is not None and end_page is not None:
            record["attributes"] = {
                "chunk_type": "page_range",
                "start_page": start_page,
                "end_page": end_page
            }

        if extraction_type in ["boxes", "polygons", "mixed"]:
            record["unit"] = "per_mille"

        page_width = self._format_dimension(chunk_widths)
        if page_width is not None:
            record["page_width"] = page_width

        page_height = self._format_dimension(chunk_heights)
        if page_height is not None:
            record["page_height"] = page_height

        return record

    def main(
        self, 
        password: str | None = None, 
        strict: bool = False, 
        use_ocr: bool = False, 
        ocr_language: str = "eng",
        max_blocks_per_record: int | None = 100_000
    ) -> list[dict[str, Any]] | None:
        """
        Args:
            password (str | None): Optional password for decrypting secured PDFs. Defaults to None.
            strict (bool): If True, enforces strict parsing and raises exceptions on malformed PDF streams. 
                Defaults to False.
            use_ocr (bool): If True, runs a fallback OCR engine on pages lacking extractable text. 
                Defaults to False.
            ocr_language (str): The Tesseract/OCR language code (e.g., 'eng') to use for fallback extraction. 
                Defaults to "eng".
            max_blocks_per_record (int | None): The maximum number of geometric blocks permitted per output record. 
                Note: this matches the `open/document-extraction` limit; increasing this value will permit non-schema-valid payloads.

        Returns:
            list[dict[str, Any]] | None: A list of schema-valid `document-extraction` dictionaries. 
                Each dictionary represents a contiguous chunk of the document. Returns `None` if the 
                foundational PDF extraction catastrophically fails.
        """
        try:
            pages = extract_pdf_layout_per_mille(
                self.file_path, 
                password=password, 
                strict=strict
            )
        except Exception as e:
            self.set_error(f"PDF extraction failed: {e}")
            return None

        all_blocks = []
        global_page_widths_map = {}
        global_page_heights_map = {}
        empty_pages = []

        for page in pages:
            global_page_widths_map.setdefault(page.width, []).append(page.page_number)
            global_page_heights_map.setdefault(page.height, []).append(page.page_number)

            if not page.tokens:
                empty_pages.append(page.page_number)
                continue

            for token in page.tokens:
                x0, y0, x1, y1 = token.box
                all_blocks.append({
                    "id": str(uuid.uuid4()),
                    "block_type": "box",
                    "text": token.text.strip()[:4096],
                    "page_number": page.page_number,
                    "box": {
                        "x": x0, 
                        "y": y0, 
                        "width": max(0, x1 - x0), 
                        "height": max(0, y1 - y0)
                    }
                })

        if use_ocr and empty_pages:
            logger.info(f"Running fallback OCR on {len(empty_pages)} empty pages...")
            try:
                ocr_results = ocr_extract_pdf_text(
                    self.file_path, 
                    language=ocr_language, 
                    password=password
                )
                
                for page_num in empty_pages:
                    ocr_index = page_num - 1  
                    if ocr_index < len(ocr_results):
                        text = ocr_results[ocr_index].strip()
                        if text:
                            all_blocks.append({
                                "id": str(uuid.uuid4()),
                                "block_type": "text",  
                                "text": text[:4096],
                                "page_number": page_num
                            })
            except Exception as e:
                logger.warning(f"Fallback OCR failed: {e}")

        all_blocks.sort(key=lambda x: x.get("page_number", 0))

        if not all_blocks:
            return [self._build_record([], global_page_widths_map, global_page_heights_map)]

        if max_blocks_per_record is None or max_blocks_per_record <= 0:
            return [self._build_record(all_blocks, global_page_widths_map, global_page_heights_map)]

        results = []
        for i in range(0, len(all_blocks), max_blocks_per_record):
            chunk_slice = all_blocks[i : i + max_blocks_per_record]
            record = self._build_record(
                blocks=chunk_slice,
                global_widths=global_page_widths_map,
                global_heights=global_page_heights_map
            )
            results.append(record)

        return results