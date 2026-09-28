"""Synthetic bead images with known ground truth for tests."""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class TruthBead:
    x: int
    y: int
    diameter: int


def make_bead_image(
    size: int = 900,
    dish_radius: int = 400,
    diameters: tuple[int, ...] = (20, 24, 28, 32, 36),
    spacing: int = 50,
    touching_pairs: int = 3,
) -> tuple[np.ndarray, list[TruthBead], tuple[int, int, int]]:
    """Grey background, dark dish, bright beads on a grid. Returns (BGR image, beads, dish)."""
    img = np.full((size, size, 3), 110, np.uint8)
    cx = cy = size // 2
    cv2.circle(img, (cx, cy), dish_radius, (25, 25, 25), -1)

    beads: list[TruthBead] = []
    i = 0
    steps = (dish_radius - spacing) // spacing
    for ky in range(-steps, steps + 1):
        y = cy + ky * spacing
        for kx in range(-steps, steps + 1):
            x = cx + kx * spacing
            if (x - cx) ** 2 + (y - cy) ** 2 <= (dish_radius - spacing) ** 2:
                d = diameters[i % len(diameters)]
                cv2.circle(img, (x, y), d // 2, (230, 230, 230), -1)
                beads.append(TruthBead(x, y, d))
                i += 1

    # A few touching pairs between grid rows and columns so they overlap nothing else.
    px = cx - spacing * 2 + spacing // 2
    py = cy + spacing // 2
    for k in range(touching_pairs):
        d = 24
        x1 = px + k * spacing * 2
        cv2.circle(img, (x1, py), d // 2, (230, 230, 230), -1)
        cv2.circle(img, (x1 + d - 1, py), d // 2, (230, 230, 230), -1)
        beads.append(TruthBead(x1, py, d))
        beads.append(TruthBead(x1 + d - 1, py, d))

    return img, beads, (cx, cy, dish_radius)


def encode_jpeg(image: np.ndarray, quality: int = 95) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return bytes(buf)


def encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return bytes(buf)


def to_bytes_io(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
