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
        """Assembles the extracted blocks and dimensions into the final schema-valid dictionary."""
        has_boxes = any(b.get("block_type") == "box" for b in blocks)
        has_text = any(b.get("block_type") == "text" for b in blocks)

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
        
        if extraction_type in ["boxes", "polygons", "mixed"]:
            record["unit"] = "per_mille"

        page_width = self._format_dimension(global_widths)
        if page_width is not None:
            record["page_width"] = page_width

        page_height = self._format_dimension(global_heights)
        if page_height is not None:
            record["page_height"] = page_height

        all_pages = [p for p_list in global_widths.values() for p in p_list]
        if all_pages:
            record["attributes"] = {
                "chunk_type": "page_range",
                "start_page": min(all_pages),
                "end_page": max(all_pages)
            }

        return record

    def main(
        self, 
        password: str | None = None, 
        strict: bool = False, 
        use_ocr: bool = False, 
        ocr_language: str = "eng"
    ) -> dict[str, Any] | None:
        """
        Dorsal model for deterministic PDF text and layout extraction.

        Args:
            password (str | None): Optional password for decrypting secured PDFs.
            strict (bool): If True, enforces strict parsing and raises exceptions on malformed streams. 
            use_ocr (bool): If True, runs a fallback OCR engine on pages lacking extractable text. 
            ocr_language (str): The Tesseract/OCR language code (e.g., 'eng').

        Returns:
            dict[str, Any] | None: A single schema-valid `document-extraction` dictionary 
                representing the entire document. The framework will automatically chunk it 
                if it breaches schema limits.
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
                clean_text = token.text.strip()

                if len(clean_text) > 4096:
                    self.log_debug(
                        "Truncating text in block on page %s (length %d > 4096 limit). Begins: %s", 
                        page.page_number, 
                        len(clean_text),
                        clean_text[:50]
                    )
                    clean_text = clean_text[:4096]

                x0, y0, x1, y1 = token.box
                all_blocks.append({
                    "id": str(uuid.uuid4()),
                    "block_type": "box",
                    "text": clean_text,
                    "page_number": page.page_number,
                    "box": {
                        "x": x0, 
                        "y": y0, 
                        "width": max(0, x1 - x0), 
                        "height": max(0, y1 - y0)
                    }
                })

        if use_ocr and empty_pages:
            self.log_debug("Running fallback OCR on %d empty pages...", len(empty_pages))
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
                            if len(text) > 4096:
                                self.log_debug(
                                    "Truncating OCR text on page %s (length %d > 4096 limit). Begins: %s", 
                                    page_num, 
                                    len(text),
                                    text[:50]
                                )
                                text = text[:4096]

                            all_blocks.append({
                                "id": str(uuid.uuid4()),
                                "block_type": "text",  
                                "text": text,
                                "page_number": page_num
                            })
            except Exception as e:
                self.log_warning("Fallback OCR failed: %s", e)

        all_blocks.sort(key=lambda x: x.get("page_number", 0))

        return self._build_record(all_blocks, global_page_widths_map, global_page_heights_map)