"""Bead counting and sizing with classic OpenCV segmentation.

Flow: (optionally) lens-correct or raw-render the input with RawTherapee, find the
round dish, threshold + marker-controlled watershed inside it, measure each bead,
group by diameter, and draw an overlay with red contours, index and size.
"""

from __future__ import annotations

from app.config import Settings
from app.i18n import t, tr
from app.processing import bead_common as bc
from app.processing import beads as bd
from app.processing.base import ParamOption, ParamSpec, ProcessingError, ProcessRequest, ProcessResult
from app.processing.lcp import LcpIndex
from app.processing.rawtherapee import RawTherapee

S_SHAPE = t("Shape", "Форма")
S_SEG = t("Segmentation", "Сегментация")


class BeadAnalysisMode:
    id = "bead_analysis"
    name = t("Bead count and sizes (OpenCV)", "Подсчёт и размеры шариков (OpenCV)")
    description = t(
        "Finds beads inside a round dish, counts them and measures their diameters. "
        "Output: count, size histogram, tables and an overlay with numbers and sizes in px and mm. "
        "The mm/px scale is entered manually.",
        "Находит шарики внутри круглой чашки, считает их и измеряет диаметр. "
        "Результат: количество, гистограмма по размерам, таблицы и оверлей с номерами "
        "и размерами в px и мм. Масштаб мм/px задаётся вручную.",
    )

    def __init__(self, index: LcpIndex | None, rawtherapee: RawTherapee, jpeg_quality: int = 95) -> None:
        self._index = index
        self._preparer = bc.ImagePreparer(index, rawtherapee, jpeg_quality)
        self._jpeg_quality = jpeg_quality

    @classmethod
    def from_settings(cls, settings: Settings) -> "BeadAnalysisMode":
        index: LcpIndex | None
        try:
            index = LcpIndex.load(settings.lcp_dir)
        except Exception:  # noqa: BLE001 - lens correction is optional here
            index = None
        rt = RawTherapee(settings.rawtherapee_cli, timeout=settings.process_timeout)
        return cls(index, rt, jpeg_quality=settings.jpeg_quality)

    # ------------------------------------------------------------------ params

    def params(self) -> list[ParamSpec]:
        return [
            *bc.calibration_specs(),
            *bc.size_specs(),
            ParamSpec("min_circularity", t("Min circularity (0–1)", "Мин. круглость (0–1)"), "number", 0.5,
                      help=t("4πA/P²: 1 is a perfect circle. Lower it to keep beads cut by neighbours; raise it to drop irregular blobs.",
                             "4πA/P²: 1 — идеальный круг. Ниже — остаются шарики, срезанные соседями; выше — отсекаются неровные пятна."),
                      min=0, max=1, step=0.05, section=S_SHAPE),
            ParamSpec("min_solidity", t("Min solidity (0–1)", "Мин. сплошность (0–1)"), "number", 0.8,
                      help=t("Area divided by convex hull area. Rejects concave fragments of merged beads.",
                             "Площадь / площадь выпуклой оболочки. Отсекает вогнутые фрагменты слипшихся шариков."),
                      min=0, max=1, step=0.05, section=S_SHAPE),
            ParamSpec("marker_method", t("Split touching beads by", "Разделение слипшихся"), "select", "brightness",
                      help=t("Brightness: each bead has a bright centre, good for piles. Shape: uses distance to the edge, good for a flat single layer.",
                             "По яркости: у каждого шарика светлый центр, подходит для насыпи. По форме: по расстоянию до края, подходит для плоского слоя."),
                      options=(ParamOption("brightness", t("Brightness peaks (pile)", "По яркости центров (насыпь)")),
                               ParamOption("distance", t("Shape (flat layer)", "По форме (плоский слой)"))),
                      section=S_SEG),
            ParamSpec("threshold", t("Brightness threshold, 0 = auto", "Порог яркости, 0 = авто"), "number", 0,
                      help=t("Cut-off between beads and background, 0–255. 0 picks it automatically (Otsu). Raise it if background or shadows are counted as beads; lower it if dark beads are missed.",
                             "Граница между шариками и фоном, 0–255. 0 подбирает автоматически (Otsu). Повышайте, если фон или тени считаются шариками; понижайте, если тёмные шарики пропускаются."),
                      min=0, max=255, step=1, section=S_SEG),
            ParamSpec("blur", t("Blur before threshold, px", "Размытие перед порогом, px"), "number", 5,
                      help=t("Gaussian blur radius applied before thresholding. Higher values remove noise and texture inside beads but close small gaps between touching beads. Use odd numbers.",
                             "Радиус гауссова размытия перед порогом. Больше — меньше шума и текстуры внутри шариков, но закрываются узкие зазоры между соседями. Используйте нечётные числа."),
                      min=1, max=31, step=2, section=S_SEG),
            ParamSpec("bright_beads", t("Beads are brighter than background", "Шарики светлее фона"), "bool", True,
                      help=t("Turn off for dark beads on a bright background.",
                             "Выключите для тёмных шариков на светлом фоне."),
                      section=S_SEG),
            bc.dish_spec(S_SEG),
            *bc.overlay_specs(),
            *bc.preprocess_specs(self._index),
        ]

    # ----------------------------------------------------------------- process

    def process(self, request: ProcessRequest) -> ProcessResult:
        p = request.params
        lang = request.lang
        common = bc.parse_common(p, lang)
        marker_method = bc.choice(p, "marker_method", "brightness", bd.MARKER_METHODS, lang)

        notes: list[str] = []
        logs: list[str] = []
        image, original_path = self._preparer.prepare(request, notes, logs)
        gray = bd.to_gray(image)
        dish, roi = bc.find_dish(gray, common, notes, lang)

        seg_params = bd.SegmentParams(
            min_diameter_px=common.min_px,
            max_diameter_px=common.max_px,
            min_circularity=bc.num(p, "min_circularity", 0.5, lang),
            min_solidity=bc.num(p, "min_solidity", 0.8, lang),
            blur=int(bc.num(p, "blur", 5, lang)),
            threshold=int(bc.num(p, "threshold", 0, lang)),
            marker_method=marker_method,
            bright_beads=bc.boolean(p, "bright_beads", True),
        )
        try:
            seg = bd.segment_beads(image, seg_params, roi)
        except ValueError as exc:
            raise ProcessingError(str(exc)) from exc

        logs.append(
            f"beads: {len(seg.beads)} found, {seg.rejected} rejected; threshold {seg.threshold_used:.0f}; "
            f"diameter window {seg_params.min_diameter_px:.1f}–{seg_params.max_diameter_px:.1f} px; dish {dish}"
        )
        L = lambda en, ru: tr(t(en, ru), lang)  # noqa: E731
        extra = [
            (L("Rejected segments", "Отброшено сегментов"), str(seg.rejected)),
            (L("Brightness threshold", "Порог яркости"), f"{seg.threshold_used:.0f}"),
        ]
        return bc.build_result(
            request, image, original_path, seg.beads, dish, common, notes, logs, extra,
            overlay_shape="contour", jpeg_quality=self._jpeg_quality,
        )
