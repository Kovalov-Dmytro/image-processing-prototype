"""Circle approximation of labelled masks.

Given a label image (0 = background, 1..N = objects, e.g. from Cellpose), each
object's outer contour is fitted with a circle by algebraic least squares
(Kåsa fit). The fitted radius gives the diameter; the relative RMS residual of
the contour points from that circle says how circular the object really is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from app.processing.beads import Bead, _label_bboxes, number_beads


def fit_circle(points: np.ndarray) -> tuple[float, float, float, float]:
    """Least-squares circle through 2-D points. Returns (cx, cy, r, relative RMS residual).

    Solves a*x + b*y + c = x² + y² in the least-squares sense, then
    cx = a/2, cy = b/2, r = sqrt(c + cx² + cy²). Needs at least 3 points.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if pts.shape[0] < 3:
        raise ValueError("at least 3 points are required to fit a circle")
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones_like(x)])
    if np.linalg.matrix_rank(A) < 3:
        raise ValueError("points are collinear, no circle fits them")
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r2 = sol[2] + cx * cx + cy * cy
    if not np.isfinite(r2) or r2 <= 0:
        raise ValueError("degenerate circle fit")
    r = math.sqrt(r2)
    dist = np.hypot(x - cx, y - cy)
    rms = float(np.sqrt(np.mean((dist - r) ** 2)))
    return float(cx), float(cy), float(r), rms / r


@dataclass(frozen=True)
class CircleParams:
    min_diameter_px: float
    max_diameter_px: float
    max_fit_error: float = 0.15  # relative RMS residual, 0 = perfect circle
    min_circularity: float = 0.3
    min_area_px: float = 9.0


def masks_to_beads(
    masks: np.ndarray,
    params: CircleParams,
    offset: tuple[int, int] = (0, 0),
    roi: np.ndarray | None = None,
) -> tuple[list[Bead], int]:
    """Fit a circle to every labelled object. Returns (accepted beads, rejected count).

    ``offset`` (x, y) shifts coordinates when ``masks`` is a crop of the full image;
    ``roi`` is an optional full-image 0/255 mask, beads whose centre falls outside
    it are dropped.
    """
    if params.min_diameter_px <= 0 or params.max_diameter_px <= params.min_diameter_px:
        raise ValueError("min_diameter_px must be > 0 and smaller than max_diameter_px")
    labels = np.asarray(masks).astype(np.int32)
    if labels.max() <= 0:
        return [], 0
    ox, oy = offset
    h, w = labels.shape
    x0, x1, y0, y1 = _label_bboxes(labels)
    beads: list[Bead] = []
    rejected = 0
    for lab in range(1, len(x0)):
        if x1[lab] < x0[lab]:
            continue
        bx0, by0 = max(0, int(x0[lab]) - 1), max(0, int(y0[lab]) - 1)
        bx1, by1 = min(w - 1, int(x1[lab]) + 1), min(h - 1, int(y1[lab]) + 1)
        sub = (labels[by0 : by1 + 1, bx0 : bx1 + 1] == lab).astype(np.uint8)
        contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < params.min_area_px or len(contour) < 5:
            rejected += 1
            continue
        contour = contour + np.array([[[bx0 + ox, by0 + oy]]], np.int32)
        try:
            cx, cy, r, fit_error = fit_circle(contour[:, 0, :])
        except (ValueError, np.linalg.LinAlgError):
            rejected += 1
            continue
        diameter = 2.0 * r
        perimeter = float(cv2.arcLength(contour, True))
        circularity = min(1.0, 4.0 * math.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0
        hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
        solidity = area / hull_area if hull_area > 0 else 0.0
        inside = True
        if roi is not None:
            ix, iy = int(round(cx)), int(round(cy))
            inside = 0 <= iy < roi.shape[0] and 0 <= ix < roi.shape[1] and roi[iy, ix] > 0
        if not (
            inside
            and params.min_diameter_px <= diameter <= params.max_diameter_px
            and fit_error <= params.max_fit_error
            and circularity >= params.min_circularity
        ):
            rejected += 1
            continue
        beads.append(Bead(0, cx, cy, diameter, area, circularity, solidity, contour, fit_error))
    number_beads(beads, params.max_diameter_px)
    return beads, rejected
