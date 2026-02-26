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
from importlib.metadata import version
from dorsal import AnnotationModel
from dorsal.file.preprocessing.pdf import extract_pdf_layout_per_mille, ocr_extract_pdf_text

logger = logging.getLogger(__name__)

class PdfExtractor(AnnotationModel):
    id = "github:dorsalhub/pdf-extractor"
    version = version("dorsal-pdf-extractor")

    def main(self, password: str | None = None, strict: bool = False, use_ocr: bool = False, ocr_language: str = "eng"):
        try:
            pages = extract_pdf_layout_per_mille(
                self.file_path, 
                password=password, 
                strict=strict
            )
        except Exception as e:
            self.set_error(f"PDF extraction failed: {e}")
            return None

        blocks = []
        page_widths_map = {}
        page_heights_map = {}
        empty_pages = []

        for page in pages:
            page_widths_map.setdefault(page.width, []).append(page.page_number)
            page_heights_map.setdefault(page.height, []).append(page.page_number)

            if not page.tokens:
                empty_pages.append(page.page_number)

            for token in page.tokens:
                x0, y0, x1, y1 = token.box
                blocks.append({
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
                            blocks.append({
                                "id": str(uuid.uuid4()),
                                "block_type": "text",  
                                "text": text[:4096],
                                "page_number": page_num
                            })
            except Exception as e:
                logger.warning(f"Fallback OCR failed: {e}")

        
        def format_dimension(dim_map):
            if not dim_map:
                return None
            if len(dim_map) == 1:
                return list(dim_map.keys())[0]
            return [{"value": v, "pages": p} for v, p in dim_map.items()]

        
        has_boxes = any(b["block_type"] == "box" for b in blocks)
        has_text = any(b["block_type"] == "text" for b in blocks)
        
        if has_boxes and has_text:
            extraction_type = "mixed"
        elif has_boxes:
            extraction_type = "boxes"
        elif has_text:
            extraction_type = "text"
        else:
            extraction_type = "boxes" 

        result = {
            "extraction_type": extraction_type,
            "producer": f"pdf-extractor-v{self.version}",
            "blocks": blocks
        }
        
        
        if extraction_type in ["boxes", "polygons", "mixed"]:
            result["unit"] = "per_mille"

        
        page_width = format_dimension(page_widths_map)
        if page_width is not None:
            result["page_width"] = page_width

        page_height = format_dimension(page_heights_map)
        if page_height is not None:
            result["page_height"] = page_height

        return result
