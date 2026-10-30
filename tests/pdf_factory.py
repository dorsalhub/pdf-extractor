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

"""Build small text PDFs for tests, using only the standard library."""

from dataclasses import dataclass, field

A4 = (0.0, 0.0, 595.0, 842.0)
LETTER = (0.0, 0.0, 612.0, 792.0)
A5_LANDSCAPE = (0.0, 0.0, 595.0, 420.0)


@dataclass
class Page:
    """A page with a MediaBox and lines of Helvetica text at (x, y) from the bottom-left corner."""

    media_box: tuple[float, float, float, float] = A4
    lines: list[tuple[float, float, str]] = field(default_factory=list)
    font_size: float = 12.0


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _number(value: float) -> str:
    return f"{value:g}"


def build_pdf(pages: list[Page]) -> bytes:
    """Return the bytes of a PDF with the given pages."""
    font_ref = 3
    first_page_ref = 4
    page_refs = [first_page_ref + 2 * i for i in range(len(pages))]

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{r} 0 R' for r in page_refs)}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]

    for page, page_ref in zip(pages, page_refs, strict=True):
        content = "".join(
            f"BT /F1 {_number(page.font_size)} Tf {_number(x)} {_number(y)} Td ({_escape(text)}) Tj ET\n"
            for x, y, text in page.lines
        ).encode("cp1252")
        box = " ".join(_number(v) for v in page.media_box)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] "
            f"/Resources << /Font << /F1 {font_ref} 0 R >> >> /Contents {page_ref + 1} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream")

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%EOF\n" % (len(objects) + 1, xref_offset)
    return bytes(out)
