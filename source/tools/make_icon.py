from __future__ import annotations

import struct
import zlib
from pathlib import Path


SIZE = 256
SCALE = 3
CANVAS = SIZE * SCALE


def rounded_rect(x: int, y: int, left: int, top: int, right: int, bottom: int, radius: int) -> bool:
    if left + radius <= x < right - radius or top + radius <= y < bottom - radius:
        return left <= x < right and top <= y < bottom
    cx = left + radius if x < left + radius else right - radius - 1
    cy = top + radius if y < top + radius else bottom - radius - 1
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def point_in_triangle(px: int, py: int, a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    point = (px, py)
    d1 = sign(point, a, b)
    d2 = sign(point, b, c)
    d3 = sign(point, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render() -> bytes:
    high: list[list[tuple[int, int, int, int]]] = []
    for y in range(CANVAS):
        row: list[tuple[int, int, int, int]] = []
        for x in range(CANVAS):
            if not rounded_rect(x, y, 24, 24, CANVAS - 24, CANVAS - 24, 150):
                row.append((0, 0, 0, 0))
                continue

            blend = (x + y) / (2 * CANVAS)
            blue = (
                int(37 * (1 - blend) + 14 * blend),
                int(99 * (1 - blend) + 165 * blend),
                int(235 * (1 - blend) + 233 * blend),
                255,
            )

            # Video play mark in the upper half.
            if point_in_triangle(x, y, (282, 170), (282, 388), (468, 279)):
                row.append((255, 255, 255, 255))
                continue

            # Download arrow and tray.
            arrow_stem = 335 <= x <= 433 and 346 <= y <= 535
            arrow_head = point_in_triangle(x, y, (252, 492), (516, 492), (384, 624))
            tray = rounded_rect(x, y, 210, 620, 558, 676, 24)
            row.append((255, 255, 255, 255) if arrow_stem or arrow_head or tray else blue)
        high.append(row)

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        for x in range(SIZE):
            samples = [high[y * SCALE + sy][x * SCALE + sx] for sy in range(SCALE) for sx in range(SCALE)]
            raw.extend(sum(pixel[channel] for pixel in samples) // len(samples) for channel in range(4))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return header + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def main() -> None:
    assets = Path(__file__).resolve().parents[1] / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    png = render()
    (assets / "app.png").write_bytes(png)
    icon_dir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    (assets / "app.ico").write_bytes(icon_dir + entry + png)


if __name__ == "__main__":
    main()
