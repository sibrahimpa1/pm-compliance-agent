"""A tiny, dependency-free PDF writer.

It supports exactly what the synthetic documents need:
- text pages drawn with the built-in Helvetica fonts (a real text layer), and
- image-only pages (a grayscale raster, no text layer) that imitate a scan.

Output is byte-for-byte deterministic: no timestamps or random IDs, so the
SHA-256 of a generated file is stable and can key the extraction fixtures.
"""
from __future__ import annotations

import zlib
from typing import List, Optional, Tuple

PAGE_W = 612  # US Letter, points
PAGE_H = 792


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class TextPage:
    def __init__(self) -> None:
        self.ops: List[str] = []

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False,
             gray: float = 0.0) -> None:
        font = "/F2" if bold else "/F1"
        self.ops.append(
            "BT %s %g Tf %.3f g %g %g Td (%s) Tj ET" % (font, size, gray, x, y, _escape(s))
        )

    def rect(self, x: float, y: float, w: float, h: float, fill: Optional[float] = None,
             stroke: Optional[float] = 0.6, width: float = 0.8) -> None:
        if fill is not None:
            self.ops.append("%.3f g %g %g %g %g re f" % (fill, x, y, w, h))
        if stroke is not None:
            self.ops.append("%.3f G %g w %g %g %g %g re S" % (stroke, width, x, y, w, h))

    def line(self, x1: float, y1: float, x2: float, y2: float, gray: float = 0.6) -> None:
        self.ops.append("%.3f G 0.8 w %g %g m %g %g l S" % (gray, x1, y1, x2, y2))

    def content(self) -> bytes:
        return ("\n".join(self.ops) + "\n").encode("latin-1")


class ImagePage:
    """A page that is one grayscale image and nothing else (no text layer)."""

    def __init__(self, width_px: int, height_px: int, pixels: bytes) -> None:
        assert len(pixels) == width_px * height_px
        self.width_px = width_px
        self.height_px = height_px
        self.pixels = pixels

    def content(self) -> bytes:
        return ("q %d 0 0 %d 0 0 cm /Im1 Do Q\n" % (PAGE_W, PAGE_H)).encode("latin-1")


class PDF:
    def __init__(self) -> None:
        self.pages: List[object] = []

    def add_page(self, page: object) -> None:
        self.pages.append(page)

    def to_bytes(self) -> bytes:
        objects: List[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")  # placeholder, filled below
        pages_obj = add(b"")
        font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                    b"/Encoding /WinAnsiEncoding >>")
        font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                    b"/Encoding /WinAnsiEncoding >>")
        kids: List[int] = []
        for page in self.pages:
            content = page.content()  # type: ignore[attr-defined]
            stream = zlib.compress(content, 9)
            content_obj = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                              + stream + b"\nendstream")
            if isinstance(page, ImagePage):
                img = zlib.compress(page.pixels, 9)
                img_obj = add(
                    b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
                    b"/Length %d >>\nstream\n" % (page.width_px, page.height_px, len(img))
                    + img + b"\nendstream")
                resources = b"<< /XObject << /Im1 %d 0 R >> >>" % img_obj
            else:
                resources = b"<< /Font << /F1 %d 0 R /F2 %d 0 R >> >>" % (font1, font2)
            page_obj = add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources %s "
                b"/Contents %d 0 R >>" % (pages_obj, PAGE_W, PAGE_H, resources, content_obj))
            kids.append(page_obj)
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
        objects[pages_obj - 1] = (b"<< /Type /Pages /Kids [%s] /Count %d >>"
                                  % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, catalog, xref))
        return bytes(out)


# --- a 5x7 bitmap font, used only to paint the "scanned" page ------------------
_GLYPHS = {
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11), "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E), "D": (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F), "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F), "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E), "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11), "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11), "N": (0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E), "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D), "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E), "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E), "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A), "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04), "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E), "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F), "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02), "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E), "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E), "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00), "/": (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x00),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00), ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08), "$": (0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04),
    "#": (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A), "&": (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02), ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    " ": (0, 0, 0, 0, 0, 0, 0),
}


def raster_page(lines: List[tuple], width: int = 1224, height: int = 1584,
                seed: int = 7) -> ImagePage:
    """Paint text lines into a grayscale raster that looks like a so-so scan.

    `lines` is a list of (text, scale[, smudge_from_char]). Text is upper-cased; unknown characters
    become blanks. Light deterministic speckle imitates scanner noise.
    """
    buf = bytearray([236]) * (width * height)
    state = seed
    for i in range(0, width * height, 7):  # deterministic speckle
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        if state % 23 == 0:
            buf[i] = 200 + (state % 30)
    y = 90
    for item in lines:
        text, scale = item[0], item[1]
        smudge_from = item[2] if len(item) > 2 else None  # type: ignore[misc]
        if smudge_from is not None:  # a grey blot over part of the line
            x0 = 80 + smudge_from * 6 * scale
            for yy in range(y - 6, y + 7 * scale + 6):
                for xx in range(x0, min(width, x0 + 11 * 6 * scale)):
                    d = abs(yy - (y + 3 * scale)) + abs(xx - x0 - 40) // 6
                    if d < 14 + (xx * 7 + yy * 3) % 5:
                        buf[yy * width + xx] = 150 + (xx * 13 + yy * 7) % 40
        x = 80
        for ch in text.upper():
            glyph = _GLYPHS.get(ch, _GLYPHS[" "])
            for row, bits in enumerate(glyph):
                for col in range(5):
                    if bits & (0x10 >> col) and x + (col + 1) * scale < width:
                        for dy in range(scale):
                            base = (y + row * scale + dy) * width + x + col * scale
                            for dx in range(scale):
                                if 0 <= base + dx < len(buf) and y + row * scale < height:
                                    buf[base + dx] = 40
            x += 6 * scale
        y += 7 * scale + 14
    return ImagePage(width, height, bytes(buf))
