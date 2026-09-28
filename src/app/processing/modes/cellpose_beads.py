"""Bead counting and sizing with Cellpose 3 segmentation and circle approximation.

Same task and report as ``bead_analysis`` but a different algorithm: a Cellpose 3
network (cyto3 by default) produces one mask per bead, then each mask's outline
is fitted with a least-squares circle whose diameter is the bead size. Works
without a GPU; the network runs on the CPU inside the Docker image.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from app.config import Settings
from app.i18n import t, tr
from app.processing import bead_common as bc
from app.processing import beads as bd
from app.processing.base import ParamOption, ParamSpec, ProcessingError, ProcessRequest, ProcessResult
from app.processing.circles import CircleParams, masks_to_beads
from app.processing.lcp import LcpIndex
from app.processing.rawtherapee import RawTherapee

log = logging.getLogger(__name__)

S_CP = t("Cellpose", "Cellpose")
S_FIT = t("Circle fit", "Аппроксимация кругом")
MODEL_TYPES = ("cyto3", "cyto2", "nuclei")


class CellposeBeadsMode:
    id = "cellpose_beads"
    name = t("Beads via Cellpose 3 + circle fit", "Шарики через Cellpose 3 + аппроксимация круга")
    description = t(
        "Same task as the OpenCV mode with a different algorithm: a Cellpose 3 neural network "
        "segments every bead, then a least-squares circle is fitted to each outline and its "
        "diameter is reported. Runs on the CPU, expect tens of seconds for a 12 MP photo.",
        "Та же задача, что у режима OpenCV, но другим алгоритмом: нейросеть Cellpose 3 выделяет "
        "каждый шарик, затем к его контуру по методу наименьших квадратов подбирается окружность, "
        "и её диаметр идёт в отчёт. Работает на CPU, для снимка 12 Мп ожидайте десятки секунд.",
    )

    def __init__(self, index: LcpIndex | None, rawtherapee: RawTherapee, jpeg_quality: int = 95) -> None:
        self._index = index
        self._preparer = bc.ImagePreparer(index, rawtherapee, jpeg_quality)
        self._jpeg_quality = jpeg_quality
        self._models: dict[tuple[str, bool], Any] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "CellposeBeadsMode":
        index: LcpIndex | None
        try:
            index = LcpIndex.load(settings.lcp_dir)
        except Exception:  # noqa: BLE001 - lens correction is optional here
            index = None
        rt = RawTherapee(settings.rawtherapee_cli, timeout=settings.process_timeout)
        return cls(index, rt, jpeg_quality=settings.jpeg_quality)

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("cellpose") is not None

    # ------------------------------------------------------------------ params

    def params(self) -> list[ParamSpec]:
        return [
            *bc.calibration_specs(),
            *bc.size_specs(),
            ParamSpec("model_type", t("Cellpose model", "Модель Cellpose"), "select", "cyto3",
                      help=t("cyto3 is the general Cellpose 3 model and the best default; cyto2 is the older one; nuclei suits round blobs on a dark background.",
                             "cyto3 — общая модель Cellpose 3, лучший вариант по умолчанию; cyto2 — предыдущая; nuclei подходит для круглых пятен на тёмном фоне."),
                      options=tuple(ParamOption(m, m) for m in MODEL_TYPES), section=S_CP),
            ParamSpec("cp_diameter_px", t("Expected diameter for Cellpose, px (0 = from size range)", "Ожидаемый диаметр для Cellpose, px (0 = из диапазона)"),
                      "number", 0,
                      help=t("Cellpose rescales the image so objects match this size. 0 uses the middle of the min/max range converted to pixels.",
                             "Cellpose масштабирует изображение под этот размер. 0 — середина диапазона мин/макс, переведённая в пиксели."),
                      min=0, max=1000, step=1, section=S_CP),
            ParamSpec("flow_threshold", t("Flow threshold", "Порог потока"), "number", 0.4,
                      help=t("Maximum allowed error of the predicted flows per mask. Raise it (up to ~1) to keep more, less regular masks; lower it to be stricter.",
                             "Допустимая ошибка предсказанных потоков для маски. Больше (до ~1) — остаётся больше менее правильных масок; меньше — строже."),
                      min=0, max=3, step=0.1, section=S_CP),
            ParamSpec("cellprob_threshold", t("Cell probability threshold", "Порог вероятности объекта"), "number", 0.0,
                      help=t("From −6 to 6. Lower it to grow masks and find dimmer beads; raise it to shrink masks and drop weak detections.",
                             "От −6 до 6. Меньше — маски растут и находятся тусклые шарики; больше — маски сжимаются, слабые находки отбрасываются."),
                      min=-6, max=6, step=0.5, section=S_CP),
            ParamSpec("downscale", t("Downscale factor", "Коэффициент уменьшения"), "number", 1,
                      help=t("Analyse a smaller copy of the image; sizes are scaled back. Saves memory and some time, but not 4× per step: Cellpose itself rescales objects to ~30 px before inference. Keep beads at least ~12 px after scaling.",
                             "Анализировать уменьшенную копию; размеры пересчитываются обратно. Экономит память и часть времени, но не в 4 раза: Cellpose сам приводит объекты к ~30 px перед расчётом. После уменьшения шарик должен оставаться не меньше ~12 px."),
                      min=1, max=8, step=1, section=S_CP),
            ParamSpec("use_gpu", t("Use GPU if available", "Использовать GPU, если есть"), "bool", False,
                      help=t("CUDA or Apple MPS. Inside the Docker image there is no GPU, so this has no effect there.",
                             "CUDA или Apple MPS. Внутри Docker-образа GPU нет, там параметр ничего не меняет."),
                      section=S_CP),
            bc.dish_spec(S_CP),
            ParamSpec("max_fit_error", t("Max circle fit error (0–1)", "Макс. ошибка аппроксимации (0–1)"), "number", 0.15,
                      help=t("RMS distance of the outline from the fitted circle divided by the radius. 0.05 keeps only near-perfect circles; 0.3 also keeps partly hidden beads.",
                             "Среднеквадратичное отклонение контура от подобранной окружности, делённое на радиус. 0.05 оставляет только почти идеальные круги; 0.3 сохраняет и частично скрытые шарики."),
                      min=0, max=1, step=0.01, section=S_FIT),
            ParamSpec("min_circularity", t("Min circularity (0–1)", "Мин. круглость (0–1)"), "number", 0.3,
                      help=t("4πA/P² of the mask outline. A loose secondary filter; the fit error above is the main one.",
                             "4πA/P² контура маски. Вспомогательный фильтр; основной — ошибка аппроксимации выше."),
                      min=0, max=1, step=0.05, section=S_FIT),
            *bc.overlay_specs(),
            *bc.preprocess_specs(self._index),
        ]

    # ----------------------------------------------------------------- model

    def _model(self, model_type: str, gpu: bool, lang: str):
        key = (model_type, gpu)
        with self._lock:
            if key in self._models:
                return self._models[key]
            try:
                logging.getLogger("cellpose").setLevel(logging.WARNING)
                models = importlib.import_module("cellpose.models")
            except Exception as exc:  # noqa: BLE001
                raise ProcessingError(
                    tr(t(f"Cellpose is not available: {exc}", f"Cellpose недоступен: {exc}"), lang)
                ) from exc
            t0 = time.time()
            model = models.CellposeModel(gpu=gpu, model_type=model_type)
            log.info("loaded cellpose model %s (gpu=%s) in %.1f s", model_type, gpu, time.time() - t0)
            self._models[key] = model
            return model

    # ----------------------------------------------------------------- process

    def process(self, request: ProcessRequest) -> ProcessResult:
        p = request.params
        lang = request.lang
        common = bc.parse_common(p, lang)
        model_type = bc.choice(p, "model_type", "cyto3", MODEL_TYPES, lang)
        flow_threshold = bc.num(p, "flow_threshold", 0.4, lang)
        cellprob_threshold = bc.num(p, "cellprob_threshold", 0.0, lang)
        downscale = max(1, int(bc.num(p, "downscale", 1, lang)))
        use_gpu = bc.boolean(p, "use_gpu", False)
        cp_diameter = bc.num(p, "cp_diameter_px", 0, lang)
        if cp_diameter <= 0:
            cp_diameter = (common.min_px + common.max_px) / 2.0
        fit = CircleParams(
            min_diameter_px=common.min_px,
            max_diameter_px=common.max_px,
            max_fit_error=bc.num(p, "max_fit_error", 0.15, lang),
            min_circularity=bc.num(p, "min_circularity", 0.3, lang),
        )

        notes: list[str] = []
        logs: list[str] = []
        image, original_path = self._preparer.prepare(request, notes, logs)
        gray = bd.to_gray(image)
        dish, roi = bc.find_dish(gray, common, notes, lang)

        # Work on the dish's bounding box only: fewer pixels for the network.
        h, w = gray.shape[:2]
        if dish is not None:
            margin = int(common.max_px)
            x0, y0 = max(0, dish.cx - dish.radius - margin), max(0, dish.cy - dish.radius - margin)
            x1, y1 = min(w, dish.cx + dish.radius + margin), min(h, dish.cy + dish.radius + margin)
        else:
            x0, y0, x1, y1 = 0, 0, w, h
        crop = gray[y0:y1, x0:x1]
        work = crop
        if downscale > 1:
            work = cv2.resize(crop, (max(1, crop.shape[1] // downscale), max(1, crop.shape[0] // downscale)),
                              interpolation=cv2.INTER_AREA)
        model = self._model(model_type, use_gpu, lang)
        t0 = time.time()
        try:
            masks = model.eval(
                work,
                diameter=cp_diameter / downscale,
                channels=[0, 0],
                flow_threshold=flow_threshold,
                cellprob_threshold=cellprob_threshold,
            )[0]
        except Exception as exc:  # noqa: BLE001 - surface torch/cellpose errors to the UI
            raise ProcessingError(tr(t(f"Cellpose failed: {exc}", f"Cellpose завершился с ошибкой: {exc}"), lang)) from exc
        elapsed = time.time() - t0
        masks = np.asarray(masks).astype(np.int32)
        if downscale > 1:
            masks = cv2.resize(masks, (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST)
        n_masks = int(masks.max())

        beads, rejected = masks_to_beads(masks, fit, offset=(x0, y0), roi=roi)
        logs.append(
            f"cellpose {model_type}: {work.shape[1]}x{work.shape[0]} px (downscale {downscale}), "
            f"diameter {cp_diameter / downscale:.1f} px, flow {flow_threshold}, cellprob {cellprob_threshold}, "
            f"{n_masks} masks in {elapsed:.1f} s; circle fit kept {len(beads)}, rejected {rejected}"
        )
        L = lambda en, ru: tr(t(en, ru), lang)  # noqa: E731
        extra = [
            (L("Cellpose masks", "Масок Cellpose"), str(n_masks)),
            (L("Rejected by circle fit", "Отброшено аппроксимацией"), str(rejected)),
            (L("Cellpose time", "Время Cellpose"), f"{elapsed:.1f} s"),
            (L("Cellpose diameter", "Диаметр для Cellpose"), f"{cp_diameter:.1f} px"),
        ]
        if beads:
            mean_fit = float(np.mean([b.fit_error for b in beads]))
            extra.append((L("Mean fit error", "Средняя ошибка аппроксимации"), f"{mean_fit:.3f}"))
        return bc.build_result(
            request, image, original_path, beads, dish, common, notes, logs, extra,
            overlay_shape="circle", jpeg_quality=self._jpeg_quality,
        )
