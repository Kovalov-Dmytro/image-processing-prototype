"""Bead detection and measurement with OpenCV.

Pure functions over in-memory arrays so they can be tested without a server:

    detect_dish      find the round container to restrict the analysis region
    segment_beads    threshold + marker-controlled watershed + per-object measures
    build_histogram  group diameters into fixed-width bins
    draw_overlay     red contours, index and size labels on a copy of the image

Beads are assumed to be brighter than the background (invert with
``bright_beads=False`` otherwise). Touching beads are split by watershed seeded
either from local brightness maxima (works for piled beads, each has a bright
centre) or from distance-transform peaks (works for flat, well separated beads).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

MARKER_METHODS = ("brightness", "distance")


@dataclass(frozen=True)
class Dish:
    cx: int
    cy: int
    radius: int

    @property
    def diameter(self) -> int:
        return self.radius * 2


@dataclass
class Bead:
    index: int
    x: float
    y: float
    diameter_px: float
    area_px: float
    circularity: float
    solidity: float
    contour: np.ndarray = field(repr=False)
    fit_error: float = 0.0  # relative RMS residual of a fitted circle (0 when not fitted)


@dataclass(frozen=True)
class SegmentParams:
    min_diameter_px: float
    max_diameter_px: float
    min_circularity: float = 0.5
    min_solidity: float = 0.8
    blur: int = 5
    threshold: int = 0  # 0 = Otsu, else 1..255 manual
    marker_method: str = "brightness"
    bright_beads: bool = True


@dataclass
class SegmentResult:
    beads: list[Bead]
    rejected: int
    threshold_used: float
    mask: np.ndarray = field(repr=False)


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def detect_dish(gray: np.ndarray, work_size: int = 800) -> Dish | None:
    """Largest strong circle in the image, found with a Hough transform on a downscaled copy."""
    h, w = gray.shape[:2]
    scale = work_size / max(w, h)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (9, 9), 2)
    min_side = min(small.shape[:2])
    circles = cv2.HoughCircles(
        small,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_side // 4,
        param1=100,
        param2=40,
        minRadius=int(min_side * 0.2),
        maxRadius=int(min_side * 0.5),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    cx, cy, r = circles[0][0]
    return Dish(int(round(cx / scale)), int(round(cy / scale)), int(round(r / scale)))


def dish_mask(shape: tuple[int, ...], dish: Dish, shrink: float = 0.98) -> np.ndarray:
    mask = np.zeros(shape[:2], np.uint8)
    cv2.circle(mask, (dish.cx, dish.cy), max(1, int(dish.radius * shrink)), 255, -1)
    return mask


def _odd(value: int) -> int:
    value = int(value)
    return value if value % 2 == 1 else value + 1


def _label_bboxes(labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bounding boxes for every label id (index = label). Empty labels have x1 < x0."""
    h, w = labels.shape
    ys, xs = np.nonzero(labels)
    ids = labels[ys, xs]
    n = int(labels.max()) + 1 if ids.size else 1
    x0 = np.full(n, w, np.int64)
    x1 = np.full(n, -1, np.int64)
    y0 = np.full(n, h, np.int64)
    y1 = np.full(n, -1, np.int64)
    if ids.size:
        np.minimum.at(x0, ids, xs)
        np.maximum.at(x1, ids, xs)
        np.minimum.at(y0, ids, ys)
        np.maximum.at(y1, ids, ys)
    return x0, x1, y0, y1


def segment_beads(
    image: np.ndarray,
    params: SegmentParams,
    roi: np.ndarray | None = None,
) -> SegmentResult:
    """Detect beads in a BGR or grayscale image. ``roi`` is an optional 0/255 mask."""
    if params.marker_method not in MARKER_METHODS:
        raise ValueError(f"unknown marker method: {params.marker_method}")
    if params.min_diameter_px <= 0 or params.max_diameter_px <= params.min_diameter_px:
        raise ValueError("min_diameter_px must be > 0 and smaller than max_diameter_px")

    gray = to_gray(image)
    if not params.bright_beads:
        gray = cv2.bitwise_not(gray)
    bgr = image if image.ndim == 3 else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    blur_k = _odd(max(1, params.blur))
    blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0) if blur_k > 1 else gray
    if params.threshold > 0:
        thr_value = float(params.threshold)
        _, mask = cv2.threshold(blurred, params.threshold, 255, cv2.THRESH_BINARY)
    else:
        thr_value, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if roi is not None:
        mask = cv2.bitwise_and(mask, roi)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    min_d = params.min_diameter_px
    if params.marker_method == "distance":
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        k = _odd(max(3, int(min_d * 0.8)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        peaks = (dist == cv2.dilate(dist, kernel)) & (dist > min_d * 0.25)
    else:
        sigma = max(0.8, min_d / 4)
        smooth = cv2.GaussianBlur(gray, (0, 0), sigma)
        k = _odd(max(3, int(min_d * 0.7)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        peaks = (smooth == cv2.dilate(smooth, kernel)) & (mask > 0)
    peaks = peaks.astype(np.uint8)

    _, peak_labels = cv2.connectedComponents(peaks)
    sure_bg = cv2.erode(cv2.bitwise_not(mask), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    markers = np.zeros(gray.shape, np.int32)
    markers[sure_bg > 0] = 1
    markers[peak_labels > 0] = peak_labels[peak_labels > 0] + 1
    cv2.watershed(bgr, markers)

    labels = markers.copy()
    labels[labels <= 1] = 0
    x0, x1, y0, y1 = _label_bboxes(labels)

    beads: list[Bead] = []
    rejected = 0
    h, w = labels.shape
    ring = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    for lab in range(2, len(x0)):
        if x1[lab] < x0[lab]:
            continue
        # Watershed marks a 1 px boundary between objects; give it back to the object
        # so measured diameters are not biased low.
        bx0, by0 = max(0, int(x0[lab]) - 1), max(0, int(y0[lab]) - 1)
        bx1, by1 = min(w - 1, int(x1[lab]) + 1), min(h - 1, int(y1[lab]) + 1)
        sub = (labels[by0 : by1 + 1, bx0 : bx1 + 1] == lab).astype(np.uint8)
        sub = cv2.dilate(sub, ring)
        contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea) + np.array([[[bx0, by0]]], np.int32)
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        if area < 3 or perimeter <= 0:
            continue
        diameter = 2.0 * math.sqrt(area / math.pi)
        circularity = min(1.0, 4.0 * math.pi * area / (perimeter * perimeter))
        hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
        solidity = area / hull_area if hull_area > 0 else 0.0
        if not (
            min_d <= diameter <= params.max_diameter_px
            and circularity >= params.min_circularity
            and solidity >= params.min_solidity
        ):
            rejected += 1
            continue
        moments = cv2.moments(contour)
        if moments["m00"] > 0:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        else:
            cx, cy = float(contour[:, 0, 0].mean()), float(contour[:, 0, 1].mean())
        beads.append(Bead(0, cx, cy, diameter, area, circularity, solidity, contour))

    number_beads(beads, params.max_diameter_px)
    return SegmentResult(beads=beads, rejected=rejected, threshold_used=float(thr_value), mask=mask)


def number_beads(beads: list[Bead], row_height: float) -> None:
    """Number beads in reading order: rows of roughly one bead height, left to right."""
    row_height = max(1.0, row_height)
    beads.sort(key=lambda b: (int(b.y // row_height), b.x))
    for i, bead in enumerate(beads, 1):
        bead.index = i


def build_histogram(
    values: list[float], bin_width: float, lo: float, hi: float
) -> list[dict]:
    """Fixed-width bins covering [lo, hi]. Values outside are clamped into the edge bins."""
    if bin_width <= 0 or hi <= lo:
        raise ValueError("bin_width must be > 0 and hi > lo")
    n_bins = max(1, int(math.ceil((hi - lo) / bin_width - 1e-9)))
    counts = [0] * n_bins
    for v in values:
        idx = int((v - lo) // bin_width)
        idx = min(max(idx, 0), n_bins - 1)
        counts[idx] += 1
    total = len(values)
    bins = []
    for i, count in enumerate(counts):
        b_lo = lo + i * bin_width
        b_hi = min(hi, b_lo + bin_width)
        bins.append(
            {
                "lo": round(b_lo, 4),
                "hi": round(b_hi, 4),
                "count": count,
                "percent": round(100.0 * count / total, 1) if total else 0.0,
            }
        )
    return bins


def draw_overlay(
    image: np.ndarray,
    beads: list[Bead],
    dish: Dish | None,
    mm_per_px: float,
    label_mode: str = "number_size",
    label_scale: float = 1.0,
    thickness: int = 2,
    shape: str = "contour",
) -> np.ndarray:
    """Red outlines (measured contour or fitted circle), optional labels, optional dish outline."""
    out = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    red = (0, 0, 255)
    if dish is not None:
        cv2.circle(out, (dish.cx, dish.cy), dish.radius, (0, 200, 0), max(1, thickness))
    if shape == "circle":
        for b in beads:
            cv2.circle(out, (int(round(b.x)), int(round(b.y))), max(1, int(round(b.diameter_px / 2))), red, thickness, cv2.LINE_AA)
    else:
        cv2.drawContours(out, [b.contour for b in beads], -1, red, thickness)
    if label_mode == "none" or not beads:
        return out

    median_d = float(np.median([b.diameter_px for b in beads]))
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.2, median_d / 80.0) * label_scale
    font_thick = 1 if font_scale < 0.8 else 2
    halo = (255, 255, 255)

    def put(text: str, cx: int, baseline_y: int, scale: float) -> int:
        (tw, th), _ = cv2.getTextSize(text, font, scale, font_thick)
        org = (cx - tw // 2, baseline_y)
        cv2.putText(out, text, org, font, scale, halo, font_thick + 1, cv2.LINE_AA)
        cv2.putText(out, text, org, font, scale, red, font_thick, cv2.LINE_AA)
        return th

    for b in beads:
        x, y = int(round(b.x)), int(round(b.y))
        if label_mode == "number_size":
            # number just above the centre, size just below: both stay inside the bead
            th = put(str(b.index), x, y - 1, font_scale)
            size = f"{b.diameter_px * mm_per_px:.2f}" if mm_per_px > 0 else f"{b.diameter_px:.0f}px"
            put(size, x, y + int(th * 0.8) + 2, font_scale * 0.8)
        else:
            th = put(str(b.index), x, y + 1, font_scale)
            _ = th
    return out
