"""Shared pieces for bead-measuring modes: parameters, input preparation, report.

A bead mode differs only in how it turns pixels into a list of ``Bead``; everything
around that (scale, size window, histogram, overlay, CSV, RAW rendering, optional
lens correction) is the same and lives here.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.i18n import t, tr
from app.processing import beads as bd
from app.processing.base import (
    ExtraFile,
    ParamOption,
    ParamSpec,
    ProcessingError,
    ProcessRequest,
    ProcessResult,
)
from app.processing.exif import is_browser_viewable, is_raw, read_meta
from app.processing.lcp import LcpIndex
from app.processing.rawtherapee import LensProfileOptions, RawTherapee, build_pp3

S_CALIB = t("Calibration", "Калибровка")
S_SIZE = t("Bead size", "Размер шариков")
S_OVERLAY = t("Overlay", "Оверлей")
S_PRE = t("Pre-processing", "Предобработка")
GROUP_RAW = t("RAW (DNG)", "RAW (DNG)")
GROUP_NON_RAW = t("JPEG / TIFF / PNG", "JPEG / TIFF / PNG")


# ------------------------------------------------------------------ parsing


def num(params: dict[str, Any], name: str, default: float, lang: str) -> float:
    value = params.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProcessingError(
            tr(t(f"Parameter {name} must be a number.", f"Параметр {name} должен быть числом."), lang)
        ) from exc


def boolean(params: dict[str, Any], name: str, default: bool) -> bool:
    value = params.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def choice(params: dict[str, Any], name: str, default: str, allowed: tuple[str, ...], lang: str) -> str:
    value = str(params.get(name) or default)
    if value not in allowed:
        raise ProcessingError(tr(t(f"Unknown value for {name}: {value}", f"Недопустимое значение {name}: {value}"), lang))
    return value


@dataclass(frozen=True)
class CommonParams:
    mm_per_px: float
    min_mm: float
    max_mm: float
    bin_mm: float
    label_mode: str
    label_scale: float
    thickness: int
    detect_dish: bool

    @property
    def min_px(self) -> float:
        return self.min_mm / self.mm_per_px

    @property
    def max_px(self) -> float:
        return self.max_mm / self.mm_per_px


def parse_common(params: dict[str, Any], lang: str) -> CommonParams:
    mm_per_px = num(params, "mm_per_px", 0.2, lang)
    if mm_per_px <= 0:
        raise ProcessingError(tr(t("The mm/px scale must be greater than zero.",
                                   "Масштаб мм/px должен быть больше нуля."), lang))
    min_mm = num(params, "min_diameter_mm", 3.1, lang)
    max_mm = num(params, "max_diameter_mm", 6.5, lang)
    if min_mm <= 0 or max_mm <= min_mm:
        raise ProcessingError(tr(t("Min diameter must be positive and smaller than max diameter.",
                                   "Минимальный диаметр должен быть больше нуля и меньше максимального."), lang))
    bin_mm = num(params, "bin_width_mm", 0.5, lang)
    if bin_mm <= 0:
        raise ProcessingError(tr(t("Histogram bin width must be greater than zero.",
                                   "Шаг группировки должен быть больше нуля."), lang))
    return CommonParams(
        mm_per_px=mm_per_px,
        min_mm=min_mm,
        max_mm=max_mm,
        bin_mm=bin_mm,
        label_mode=choice(params, "label_mode", "none", ("number_size", "number", "none"), lang),
        label_scale=num(params, "label_scale", 1.0, lang),
        thickness=int(num(params, "line_thickness", 1, lang)),
        detect_dish=boolean(params, "detect_dish", True),
    )


# ------------------------------------------------------------------ param specs


def calibration_specs() -> list[ParamSpec]:
    return [
        ParamSpec("mm_per_px", t("Scale, mm per pixel", "Масштаб, мм на пиксель"), "number", 0.2,
                  help=t("Measure it on an object of known size. Every mm value is derived from this number.",
                         "Измерьте по объекту известного размера. Все размеры в мм считаются через это число."),
                  min=0.0001, max=100, step=0.001, section=S_CALIB),
    ]


def size_specs() -> list[ParamSpec]:
    return [
        ParamSpec("min_diameter_mm", t("Min bead diameter, mm", "Мин. диаметр шарика, мм"), "number", 3.1,
                  help=t("Smaller objects are treated as noise or fragments and skipped.",
                         "Объекты меньше этого считаются шумом или осколками и пропускаются."),
                  min=0.01, max=1000, step=0.1, section=S_SIZE),
        ParamSpec("max_diameter_mm", t("Max bead diameter, mm", "Макс. диаметр шарика, мм"), "number", 6.5,
                  help=t("Larger objects are treated as merged beads or debris and skipped.",
                         "Объекты больше этого считаются слипшимися шариками или мусором и пропускаются."),
                  min=0.01, max=1000, step=0.1, section=S_SIZE),
        ParamSpec("bin_width_mm", t("Histogram bin width, mm", "Шаг группировки, мм"), "number", 0.5,
                  help=t("Width of one size group in the histogram and the groups table.",
                         "Ширина одной группы в гистограмме и таблице групп."),
                  min=0.01, max=100, step=0.05, section=S_SIZE),
    ]


def dish_spec(section) -> ParamSpec:
    return ParamSpec("detect_dish", t("Detect the dish and count inside only", "Искать чашку и считать только внутри"),
                     "bool", True,
                     help=t("Finds the largest circle and ignores everything outside it (rim reflections, background).",
                            "Находит самый большой круг и игнорирует всё вне его (блики на ободе, фон)."),
                     section=section)


def overlay_specs() -> list[ParamSpec]:
    return [
        ParamSpec("label_mode", t("Overlay labels", "Подписи на оверлее"), "select", "none",
                  options=(ParamOption("number_size", t("Number and size", "Номер и размер")),
                           ParamOption("number", t("Number only", "Только номер")),
                           ParamOption("none", t("No labels", "Без подписей"))),
                  section=S_OVERLAY),
        ParamSpec("label_scale", t("Font size", "Размер шрифта"), "number", 1.0,
                  help=t("Multiplier; 1 fits the label inside a median-sized bead.",
                         "Множитель; при 1 подпись помещается в шарик медианного размера."),
                  min=0.3, max=3, step=0.1, section=S_OVERLAY),
        ParamSpec("line_thickness", t("Outline thickness, px", "Толщина контура, px"), "number", 1,
                  min=1, max=10, step=1, section=S_OVERLAY),
    ]


def preprocess_specs(index: LcpIndex | None) -> list[ParamSpec]:
    profile_options = tuple(
        ParamOption(value=f.id, label=f.label, group=GROUP_RAW if f.camera_raw else GROUP_NON_RAW)
        for f in (index.files if index else [])
    )
    return [
        ParamSpec("lens_correction", t("Correct distortion first (LCP)", "Сначала исправить дисторсию (LCP)"), "bool", False,
                  help=t("Requires RawTherapee. Sizes near the frame edges become more accurate. The profile is picked from EXIF unless chosen below.",
                         "Требует RawTherapee. Размеры у краёв кадра становятся точнее. Профиль подбирается по EXIF, если не выбран ниже."),
                  section=S_PRE),
        ParamSpec("profile", t("Lens profile", "Профиль объектива"), "select", None,
                  help=t("Leave empty to pick automatically from EXIF.", "Пусто — подобрать автоматически по EXIF."),
                  options=profile_options, section=S_PRE),
    ]


# ------------------------------------------------------------------ input image


class ImagePreparer:
    """Turns the uploaded file into a BGR array and decides what to show as the original."""

    def __init__(self, index: LcpIndex | None, rawtherapee: RawTherapee, jpeg_quality: int) -> None:
        self._index = index
        self._rt = rawtherapee
        self._jpeg_quality = jpeg_quality

    def _render(self, request: ProcessRequest, subdir: str, lcp_path: Path | None) -> tuple[Path, str]:
        run = self._rt.render(
            request.input_path,
            request.work_dir / subdir,
            build_pp3(LensProfileOptions(lcp_file=lcp_path, distortion=True, vignette=True)),
            jpeg_quality=self._jpeg_quality,
        )
        return run.output_path, run.log

    @staticmethod
    def _read(path: Path, lang: str) -> np.ndarray:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ProcessingError(tr(t("RawTherapee produced a file that could not be read.",
                                       "RawTherapee вернул файл, который не удалось прочитать."), lang))
        return image

    def prepare(self, request: ProcessRequest, notes: list[str], logs: list[str]) -> tuple[np.ndarray, Path | None]:
        params = request.params
        lang = request.lang
        raw = is_raw(request.input_path)

        if boolean(params, "lens_correction", False):
            if self._index is None:
                raise ProcessingError(tr(t("LCP profiles are unavailable, lens correction cannot run.",
                                           "Профили LCP недоступны, коррекцию объектива выполнить нельзя."), lang))
            profile_id = params.get("profile")
            lcp = self._index.get(str(profile_id)) if profile_id else None
            if lcp is None:
                meta = read_meta(request.input_path)
                lcp = self._index.suggest(meta.lens_model, camera_raw=raw)
                if lcp is None:
                    raise ProcessingError(tr(t(
                        "Could not pick an LCP profile from EXIF. Choose one manually or disable lens correction.",
                        "Не удалось подобрать профиль LCP по EXIF. Выберите профиль вручную или отключите коррекцию."), lang))
                notes.append(tr(t(f"Profile picked from EXIF: {lcp.label}.", f"Профиль подобран по EXIF: {lcp.label}."), lang))
            rendered, log = self._render(request, "corrected", lcp.path.resolve())
            logs.append(log)
            image = self._read(rendered, lang)
            original = request.work_dir / "original.jpg"
            rendered.replace(original)
            notes.append(tr(t("Analysis and overlay were done on the lens-corrected image.",
                              "Анализ и оверлей выполнены на изображении после коррекции объектива."), lang))
            return image, original

        if raw:
            rendered, log = self._render(request, "rendered", None)
            logs.append(log)
            image = self._read(rendered, lang)
            original = request.work_dir / "original.jpg"
            rendered.replace(original)
            notes.append(tr(t("RAW was rendered by RawTherapee without lens correction.",
                              "RAW отрисован RawTherapee без коррекции объектива."), lang))
            return image, original

        image = cv2.imread(str(request.input_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ProcessingError(tr(t("Could not read the image.", "Не удалось прочитать изображение."), lang))
        if not is_browser_viewable(request.input_path):
            original = request.work_dir / "original.jpg"
            cv2.imwrite(str(original), image, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
            return image, original
        return image, None


def find_dish(gray: np.ndarray, common: CommonParams, notes: list[str], lang: str) -> tuple[bd.Dish | None, np.ndarray | None]:
    if not common.detect_dish:
        return None, None
    dish = bd.detect_dish(gray)
    if dish is None:
        notes.append(tr(t("Dish not found; the whole frame was analysed.",
                          "Чашка не найдена, анализ выполнен по всему кадру."), lang))
        return None, None
    return dish, bd.dish_mask(gray.shape, dish)


# ------------------------------------------------------------------ result


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def build_result(
    request: ProcessRequest,
    image: np.ndarray,
    original_path: Path | None,
    beads: list[bd.Bead],
    dish: bd.Dish | None,
    common: CommonParams,
    notes: list[str],
    logs: list[str],
    extra_stats: list[tuple[str, str]],
    overlay_shape: str = "contour",
    jpeg_quality: int = 95,
) -> ProcessResult:
    lang = request.lang
    L = lambda en, ru: tr(t(en, ru), lang)  # noqa: E731
    mm = L("mm", "мм")

    overlay = bd.draw_overlay(
        image, beads, dish, common.mm_per_px,
        label_mode=common.label_mode, label_scale=common.label_scale,
        thickness=common.thickness, shape=overlay_shape,
    )
    processed_path = request.work_dir / "processed.jpg"
    cv2.imwrite(str(processed_path), overlay, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])

    diam_mm = [b.diameter_px * common.mm_per_px for b in beads]
    diam_px = [b.diameter_px for b in beads]
    hist = bd.build_histogram(diam_mm, common.bin_mm, common.min_mm, common.max_mm)

    stats: list[dict[str, str]] = [{"label": L("Beads found", "Найдено шариков"), "value": str(len(beads))}]
    if beads:
        stats += [
            {"label": L("Median diameter", "Медианный диаметр"),
             "value": f"{_fmt(statistics.median(diam_mm))} {mm} / {_fmt(statistics.median(diam_px), 1)} px"},
            {"label": L("Mean diameter", "Средний диаметр"),
             "value": f"{_fmt(statistics.fmean(diam_mm))} {mm} / {_fmt(statistics.fmean(diam_px), 1)} px"},
            {"label": L("Min diameter", "Мин. диаметр"),
             "value": f"{_fmt(min(diam_mm))} {mm} / {_fmt(min(diam_px), 1)} px"},
            {"label": L("Max diameter", "Макс. диаметр"),
             "value": f"{_fmt(max(diam_mm))} {mm} / {_fmt(max(diam_px), 1)} px"},
            {"label": L("Std deviation", "Ст. отклонение"), "value": f"{_fmt(statistics.pstdev(diam_mm))} {mm}"},
        ]
    for label, value in extra_stats:
        stats.append({"label": label, "value": value})
    stats.append({"label": L("Scale", "Масштаб"), "value": f"{common.mm_per_px:g} {mm}/px"})
    if dish is not None:
        stats.append({"label": L("Dish diameter", "Чашка, диаметр"),
                      "value": f"{dish.diameter} px / {_fmt(dish.diameter * common.mm_per_px, 1)} {mm}"})

    groups_rows = [[f"{b['lo']:.2f}–{b['hi']:.2f}", b["count"], b["percent"]] for b in hist]
    bead_rows = [
        [b.index, round(b.x), round(b.y), round(b.diameter_px, 1), round(b.diameter_px * common.mm_per_px, 2),
         round(b.circularity, 2)]
        for b in beads
    ]

    csv_path = request.work_dir / "beads.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "x_px", "y_px", "diameter_px", "diameter_mm", "area_px",
                         "circularity", "solidity", "fit_error"])
        for b in beads:
            writer.writerow([
                b.index, round(b.x, 1), round(b.y, 1), round(b.diameter_px, 2),
                round(b.diameter_px * common.mm_per_px, 3), round(b.area_px, 1),
                round(b.circularity, 3), round(b.solidity, 3), round(b.fit_error, 4),
            ])

    return ProcessResult(
        processed_path=processed_path,
        original_path=original_path,
        log="\n\n".join(logs),
        info={
            "notes": notes,
            "count": len(beads),
            "dish": None if dish is None else {"cx": dish.cx, "cy": dish.cy, "radius": dish.radius},
            "report": {
                "stats": stats,
                "histogram": {"title": L("Diameter distribution", "Распределение по диаметру"), "unit": mm, "bins": hist},
                "tables": [
                    {"title": L("Size groups", "Группы по размеру"),
                     "columns": [L("Diameter, mm", "Диаметр, мм"), L("Count", "Кол-во"), "%"], "rows": groups_rows},
                    {"title": L(f"Beads ({len(beads)})", f"Шарики ({len(beads)})"),
                     "columns": ["#", "x", "y", "Ø px", f"Ø {mm}", L("Circ.", "Кругл.")], "rows": bead_rows},
                ],
            },
        },
        files=[ExtraFile("beads.csv", csv_path, L("Download CSV", "Скачать CSV"), "text/csv")],
    )
