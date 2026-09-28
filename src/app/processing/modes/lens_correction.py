"""Lens correction with an Adobe LCP profile, rendered by RawTherapee.

Corrects geometric distortion and (when the profile has a vignette model)
vignetting. The bundled iPhone profiles carry no chromatic-aberration model,
so CA correction is not offered here yet.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.i18n import t, tr
from app.processing.base import (
    ParamOption,
    ParamSpec,
    ProcessingError,
    ProcessRequest,
    ProcessResult,
)
from app.processing.exif import is_browser_viewable, is_raw
from app.processing.lcp import LcpFile, LcpIndex
from app.processing.rawtherapee import LensProfileOptions, RawTherapee, build_pp3

GROUP_RAW = t("RAW (DNG)", "RAW (DNG)")
GROUP_NON_RAW = t("JPEG / TIFF / PNG", "JPEG / TIFF / PNG")


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class LensCorrectionMode:
    id = "lens_correction"
    name = t("Lens correction (LCP)", "Коррекция объектива (LCP)")
    description = t(
        "Removes distortion and vignetting using an Adobe LCP profile. "
        "Rendering is done by RawTherapee. For DNG files pick a profile marked RAW.",
        "Устраняет дисторсию и виньетирование по профилю Adobe LCP. "
        "Обработка выполняется RawTherapee. Для DNG выбирайте профиль с пометкой RAW.",
    )

    def __init__(self, index: LcpIndex, rawtherapee: RawTherapee, jpeg_quality: int = 95) -> None:
        self._index = index
        self._rt = rawtherapee
        self._jpeg_quality = jpeg_quality

    @classmethod
    def from_settings(cls, settings: Settings) -> "LensCorrectionMode":
        index = LcpIndex.load(settings.lcp_dir)
        rt = RawTherapee(settings.rawtherapee_cli, timeout=settings.process_timeout)
        return cls(index, rt, jpeg_quality=settings.jpeg_quality)

    @property
    def index(self) -> LcpIndex:
        return self._index

    def params(self) -> list[ParamSpec]:
        options = tuple(
            ParamOption(value=f.id, label=f.label, group=GROUP_RAW if f.camera_raw else GROUP_NON_RAW)
            for f in self._index.files
        )
        return [
            ParamSpec(
                name="profile",
                label=t("Lens profile", "Профиль объектива"),
                type="select",
                default=None,
                help=t(
                    "An .lcp file. Picked automatically from EXIF when the lens model matches.",
                    "Файл .lcp. Подбирается автоматически по EXIF, если модель объектива совпала.",
                ),
                options=options,
            ),
            ParamSpec(
                name="distortion",
                label=t("Correct distortion", "Исправить дисторсию"),
                type="bool",
                default=True,
                help=t(
                    "Straightens geometry using the profile's radial model.",
                    "Выпрямляет геометрию по радиальной модели профиля.",
                ),
            ),
            ParamSpec(
                name="vignetting",
                label=t("Correct vignetting", "Исправить виньетирование"),
                type="bool",
                default=True,
                help=t(
                    "Brightens dark corners. Works only if the profile has a vignette model.",
                    "Осветляет тёмные углы. Работает только если в профиле есть модель виньетки.",
                ),
            ),
        ]

    def _resolve_profile(self, request: ProcessRequest) -> LcpFile:
        lang = request.lang
        profile_id = request.params.get("profile")
        if not profile_id:
            raise ProcessingError(tr(t("Choose a lens profile.", "Выберите профиль объектива."), lang))
        lcp = self._index.get(str(profile_id))
        if lcp is None:
            raise ProcessingError(
                tr(t(f"Profile not found: {profile_id}", f"Профиль не найден: {profile_id}"), lang)
            )
        return lcp

    def process(self, request: ProcessRequest) -> ProcessResult:
        lang = request.lang
        lcp = self._resolve_profile(request)
        distortion = _as_bool(request.params.get("distortion"), True)
        vignetting = _as_bool(request.params.get("vignetting"), True)
        if not distortion and not vignetting:
            raise ProcessingError(
                tr(t("Enable at least one correction.", "Включите хотя бы одну коррекцию."), lang)
            )

        notes: list[str] = []
        raw_input = is_raw(request.input_path)
        if raw_input != lcp.camera_raw:
            notes.append(
                tr(
                    t(
                        "The profile is marked RAW but the file is not RAW.",
                        "Профиль помечен как RAW, а файл не RAW.",
                    )
                    if lcp.camera_raw
                    else t(
                        "The file is RAW but the profile is not marked RAW. The result may differ from expectations.",
                        "Файл RAW, а профиль не помечен как RAW. Результат может отличаться от ожидаемого.",
                    ),
                    lang,
                )
            )
        if vignetting and not lcp.has_vignette:
            notes.append(
                tr(
                    t(
                        "The selected profile has no vignette model; this correction will not apply.",
                        "В выбранном профиле нет модели виньетирования, эта коррекция не применится.",
                    ),
                    lang,
                )
            )

        after = self._rt.render(
            request.input_path,
            request.work_dir / "after",
            build_pp3(
                LensProfileOptions(
                    lcp_file=lcp.path.resolve(),
                    distortion=distortion,
                    vignette=vignetting,
                    chromatic_aberration=False,
                )
            ),
            jpeg_quality=self._jpeg_quality,
        )
        processed_path = request.work_dir / "processed.jpg"
        after.output_path.replace(processed_path)
        logs = [after.log]

        original_path: Path | None = None
        if not is_browser_viewable(request.input_path):
            # TIFF and DNG cannot be shown by the browser: render a "before" with the same
            # pipeline and lens correction turned off.
            before = self._rt.render(
                request.input_path,
                request.work_dir / "before",
                build_pp3(LensProfileOptions(lcp_file=None)),
                jpeg_quality=self._jpeg_quality,
            )
            original_path = request.work_dir / "original.jpg"
            before.output_path.replace(original_path)
            logs.append(before.log)
            notes.append(
                tr(
                    t(
                        "The original for comparison was rendered by RawTherapee without lens correction.",
                        "Оригинал для сравнения отрисован RawTherapee без коррекции объектива.",
                    ),
                    lang,
                )
            )

        return ProcessResult(
            processed_path=processed_path,
            original_path=original_path,
            log="\n\n".join(logs),
            info={
                "profile": lcp.to_dict(),
                "distortion": distortion,
                "vignetting": vignetting,
                "notes": notes,
            },
        )
