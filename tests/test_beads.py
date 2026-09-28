from __future__ import annotations

import math

import numpy as np
import pytest

from app.processing import beads as bd
from synthetic import make_bead_image


@pytest.fixture(scope="module")
def synthetic():
    return make_bead_image()


def _match(found: list[bd.Bead], truth) -> list[tuple]:
    """Pair each truth bead with the nearest detection within 6 px."""
    pairs = []
    for t in truth:
        best = min(found, key=lambda b: (b.x - t.x) ** 2 + (b.y - t.y) ** 2)
        if math.hypot(best.x - t.x, best.y - t.y) <= 6:
            pairs.append((t, best))
    return pairs


def test_detect_dish(synthetic) -> None:
    img, _, (cx, cy, r) = synthetic
    dish = bd.detect_dish(bd.to_gray(img))
    assert dish is not None
    assert abs(dish.cx - cx) <= 6 and abs(dish.cy - cy) <= 6
    assert abs(dish.radius - r) <= 12


@pytest.mark.parametrize("method", bd.MARKER_METHODS)
def test_segment_counts_and_sizes(synthetic, method: str) -> None:
    img, truth, (cx, cy, r) = synthetic
    roi = bd.dish_mask(img.shape, bd.Dish(cx, cy, r))
    params = bd.SegmentParams(min_diameter_px=14, max_diameter_px=44, marker_method=method)
    result = bd.segment_beads(img, params, roi)
    found = result.beads

    assert len(found) == len(truth), f"{method}: found {len(found)} of {len(truth)}"
    pairs = _match(found, truth)
    assert len(pairs) == len(truth)
    for t, b in pairs:
        assert abs(b.diameter_px - t.diameter) <= 0.15 * t.diameter + 1.0, (t, b.diameter_px)
        assert b.circularity > 0.6
    # Indices are 1..N, unique, in reading order (rows top to bottom).
    assert [b.index for b in found] == list(range(1, len(found) + 1))
    assert found[0].y <= found[-1].y


def test_segment_filters_reject_out_of_range(synthetic) -> None:
    img, truth, (cx, cy, r) = synthetic
    roi = bd.dish_mask(img.shape, bd.Dish(cx, cy, r))
    params = bd.SegmentParams(min_diameter_px=30, max_diameter_px=44)
    result = bd.segment_beads(img, params, roi)
    big = [t for t in truth if t.diameter >= 30]
    assert len(result.beads) == len(big)
    assert result.rejected > 0


def test_segment_validates_params(synthetic) -> None:
    img, _, _ = synthetic
    with pytest.raises(ValueError):
        bd.segment_beads(img, bd.SegmentParams(min_diameter_px=20, max_diameter_px=10))
    with pytest.raises(ValueError):
        bd.segment_beads(img, bd.SegmentParams(min_diameter_px=5, max_diameter_px=10, marker_method="magic"))


def test_dark_beads_on_bright_background(synthetic) -> None:
    img, truth, (cx, cy, r) = synthetic
    inverted = 255 - img
    roi = bd.dish_mask(img.shape, bd.Dish(cx, cy, r))
    params = bd.SegmentParams(min_diameter_px=14, max_diameter_px=44, bright_beads=False)
    result = bd.segment_beads(inverted, params, roi)
    assert len(result.beads) == len(truth)


def test_build_histogram() -> None:
    bins = bd.build_histogram([3.1, 3.2, 3.9, 6.4, 6.5, 7.0, 2.0], 1.0, 3.0, 7.0)
    assert [b["lo"] for b in bins] == [3.0, 4.0, 5.0, 6.0]
    assert [b["count"] for b in bins] == [4, 0, 0, 3]  # 2.0 and 7.0 clamp into edge bins
    assert sum(b["percent"] for b in bins) == pytest.approx(100.0, abs=0.2)
    assert bd.build_histogram([], 0.5, 0, 1)[0]["percent"] == 0.0
    with pytest.raises(ValueError):
        bd.build_histogram([1.0], 0, 0, 1)


def test_draw_overlay_marks_beads(synthetic) -> None:
    img, _, (cx, cy, r) = synthetic
    dish = bd.Dish(cx, cy, r)
    result = bd.segment_beads(img, bd.SegmentParams(14, 44), bd.dish_mask(img.shape, dish))
    for mode in ("number_size", "number", "none"):
        out = bd.draw_overlay(img, result.beads, dish, 0.2, label_mode=mode)
        assert out.shape == img.shape
        red = (out[:, :, 2] == 255) & (out[:, :, 1] == 0) & (out[:, :, 0] == 0)
        assert red.sum() > 1000
        # the input is untouched
        assert not np.array_equal(out, img)
    assert np.array_equal(bd.draw_overlay(img, [], None, 0.2), img)
