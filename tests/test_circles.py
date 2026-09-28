from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from app.processing.circles import CircleParams, fit_circle, masks_to_beads


def _circle_points(cx: float, cy: float, r: float, n: int = 64, noise: float = 0.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])
    if noise:
        pts += rng.normal(0, noise, pts.shape)
    return pts


def test_fit_circle_exact() -> None:
    cx, cy, r, err = fit_circle(_circle_points(100, 50, 20))
    assert abs(cx - 100) < 1e-6 and abs(cy - 50) < 1e-6 and abs(r - 20) < 1e-6
    assert err < 1e-9


def test_fit_circle_noisy_and_partial_arc() -> None:
    cx, cy, r, err = fit_circle(_circle_points(30, 30, 12, noise=0.3))
    assert abs(cx - 30) < 0.3 and abs(cy - 30) < 0.3 and abs(r - 12) < 0.3
    assert 0.005 < err < 0.05
    # three quarters of a circle still fits the same circle
    a = np.linspace(0, 1.5 * math.pi, 40)
    arc = np.column_stack([5 + 8 * np.cos(a), -3 + 8 * np.sin(a)])
    cx, cy, r, _ = fit_circle(arc)
    assert abs(cx - 5) < 1e-6 and abs(cy + 3) < 1e-6 and abs(r - 8) < 1e-6


def test_fit_circle_rejects_degenerate() -> None:
    with pytest.raises(ValueError):
        fit_circle(np.array([[0, 0], [1, 1]]))
    with pytest.raises((ValueError, np.linalg.LinAlgError)):
        fit_circle(np.array([[0, 0], [1, 1], [2, 2], [3, 3]]))  # collinear


def _label_image() -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Labelled disks of known size plus one ellipse and one tiny blob."""
    labels = np.zeros((400, 400), np.int32)
    truth = []
    lab = 1
    for i, (x, y, d) in enumerate([(60, 60, 30), (160, 60, 40), (260, 60, 24), (60, 160, 36), (160, 160, 28)]):
        cv2.circle(labels, (x, y), d // 2, lab, -1)
        truth.append((x, y, d))
        lab += 1
    cv2.ellipse(labels, (300, 300), (30, 12), 0, 0, 360, lab, -1)  # not a circle
    lab += 1
    labels[350, 50] = lab  # tiny blob
    return labels, truth


def test_masks_to_beads_measures_disks_and_rejects_others() -> None:
    labels, truth = _label_image()
    beads, rejected = masks_to_beads(labels, CircleParams(min_diameter_px=15, max_diameter_px=60))
    assert len(beads) == len(truth)
    assert rejected == 2  # ellipse (fit error) and tiny blob (area)
    for t in truth:
        b = min(beads, key=lambda b: (b.x - t[0]) ** 2 + (b.y - t[1]) ** 2)
        assert math.hypot(b.x - t[0], b.y - t[1]) < 1.5
        assert abs(b.diameter_px - t[2]) <= 1.5, (t, b.diameter_px)
        assert b.fit_error < 0.05
        assert b.circularity > 0.8
    assert [b.index for b in beads] == list(range(1, len(beads) + 1))


def test_masks_to_beads_offset_roi_and_size_filters() -> None:
    labels, truth = _label_image()
    roi = np.zeros((600, 600), np.uint8)
    cv2.rectangle(roi, (200, 100), (500, 500), 255, -1)  # the two left-column disks fall outside
    beads, _ = masks_to_beads(labels, CircleParams(15, 60), offset=(100, 100), roi=roi)
    # every accepted centre lies inside the roi and carries the offset
    for b in beads:
        assert roi[int(round(b.y)), int(round(b.x))] > 0
        assert b.x >= 100 and b.y >= 100
    assert len(beads) == len(truth) - 2
    # only the two largest disks pass a 34 px minimum
    big, _ = masks_to_beads(labels, CircleParams(34, 60))
    assert sorted(round(b.diameter_px) for b in big) == pytest.approx([36, 40], abs=1.5)
    with pytest.raises(ValueError):
        masks_to_beads(labels, CircleParams(20, 10))
    assert masks_to_beads(np.zeros((10, 10), np.int32), CircleParams(1, 5)) == ([], 0)
