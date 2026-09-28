from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

PROFILE_JPEG = "Apple iPhone (Apple iPhone 15 Pro back camera 9mm f2.8).lcp"


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def upload(client: TestClient, data: bytes, name: str, mime: str) -> dict:
    res = client.post("/api/uploads", files={"file": (name, data, mime)})
    assert res.status_code == 200, res.text
    return res.json()


def test_health_and_modes(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["rawtherapee"] is True
    assert health["lcp_files"] == 110
    assert "lens_correction" in health["modes"]

    modes = client.get("/api/modes").json()
    lens = next(m for m in modes if m["id"] == "lens_correction")
    names = [p["name"] for p in lens["params"]]
    assert names == ["profile", "distortion", "vignetting"]
    profile_param = next(p for p in lens["params"] if p["name"] == "profile")
    assert len(profile_param["options"]) == 110
    assert {o["group"] for o in profile_param["options"]} == {"RAW (DNG)", "JPEG / TIFF / PNG"}


def test_profiles_endpoint(client: TestClient) -> None:
    profiles = client.get("/api/profiles").json()
    assert len(profiles) == 110
    assert any(p["id"] == PROFILE_JPEG for p in profiles)


def test_index_page(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Image processing" in res.text
    assert 'lang="en"' in res.text
    assert "/static/app.js?v=" in res.text
    assert client.get("/static/app.js").status_code == 200


def test_modes_are_bilingual(client: TestClient) -> None:
    en = client.get("/api/modes").json()
    ru = client.get("/api/modes?lang=ru").json()
    header = client.get("/api/modes", headers={"Accept-Language": "ru-RU,ru;q=0.9"}).json()
    lens_en = next(m for m in en if m["id"] == "lens_correction")
    lens_ru = next(m for m in ru if m["id"] == "lens_correction")
    assert lens_en["name"] == "Lens correction (LCP)"
    assert lens_ru["name"] == "Коррекция объектива (LCP)"
    assert header[0]["name"] == ru[0]["name"]
    assert lens_en["params"][0]["label"] == "Lens profile"
    assert lens_ru["params"][0]["label"] == "Профиль объектива"
    # unknown language falls back to English
    assert client.get("/api/modes?lang=de").json()[0]["name"] == en[0]["name"]


def test_upload_rejects_unknown_extension(client: TestClient) -> None:
    res = client.post("/api/uploads", files={"file": ("x.gif", b"GIF89a", "image/gif")})
    assert res.status_code == 422


def test_upload_rejects_too_large(client: TestClient) -> None:
    big = b"\xff" * (6 * 1024 * 1024)
    res = client.post("/api/uploads", files={"file": ("big.jpg", big, "image/jpeg")})
    assert res.status_code == 413


def test_full_flow_jpeg(client: TestClient, jpeg_bytes: bytes) -> None:
    up = upload(client, jpeg_bytes, "photo.jpg", "image/jpeg")
    assert up["browser_viewable"] is True
    assert up["camera_raw"] is False
    assert up["suggested_profile"] is None  # synthetic image has no EXIF
    assert up["original_url"].endswith("/files/original")

    # Original is served straight from the upload.
    res = client.get(up["original_url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"

    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "lens_correction", "params": {"profile": PROFILE_JPEG, "distortion": True}, "lang": "ru"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["processed_url"].endswith("/files/processed")
    assert data["info"]["profile"]["id"] == PROFILE_JPEG
    assert "fake rawtherapee" in data["log"]
    assert any("виньет" in n for n in data["info"]["notes"])  # profile has no vignette model

    processed = client.get(data["processed_url"])
    assert processed.status_code == 200
    with Image.open(io.BytesIO(processed.content)) as im:
        assert im.size == (64, 48)
        # fake CLI inverts when the LCP is enabled: red square becomes cyan-ish
        r, g, b = im.getpixel((2, 2))
        assert r < 100 and g > 150 and b > 150

    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert 'filename="photo_lens_correction.jpg"' in dl.headers["content-disposition"]

    dl_orig = client.get(data["download_original_url"])
    assert dl_orig.status_code == 200
    assert 'filename="photo.jpg"' in dl_orig.headers["content-disposition"]


def test_full_flow_tiff_renders_original(client: TestClient, tiff_bytes: bytes) -> None:
    up = upload(client, tiff_bytes, "scan.tiff", "image/tiff")
    assert up["browser_viewable"] is False
    assert up["original_url"] is None
    assert client.get(f"/api/uploads/{up['id']}/files/original").status_code == 404

    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "lens_correction", "params": {"profile": PROFILE_JPEG}},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["original_url"].endswith("/files/original")
    original = client.get(data["original_url"])
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(original.content)) as im:
        r, g, b = im.getpixel((2, 2))
        assert r > 150 and g < 100  # "before" render is not inverted


def test_process_validation_errors(client: TestClient, jpeg_bytes: bytes) -> None:
    up = upload(client, jpeg_bytes, "photo.jpg", "image/jpeg")
    res = client.post(f"/api/uploads/{up['id']}/process", json={"mode": "lens_correction", "params": {}})
    assert res.status_code == 422
    assert "profile" in res.json()["detail"].lower()
    res = client.post(f"/api/uploads/{up['id']}/process", json={"mode": "lens_correction", "params": {}, "lang": "ru"})
    assert "профиль" in res.json()["detail"].lower()

    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "lens_correction", "params": {"profile": "nope.lcp"}},
    )
    assert res.status_code == 422

    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "lens_correction", "params": {"profile": PROFILE_JPEG, "distortion": False, "vignetting": False}},
    )
    assert res.status_code == 422

    res = client.post(f"/api/uploads/{up['id']}/process", json={"mode": "missing", "params": {}})
    assert res.status_code == 404

    res = client.post("/api/uploads/deadbeef/process", json={"mode": "lens_correction", "params": {}})
    assert res.status_code == 404


# ---------------------------------------------------------------- bead analysis


def test_bead_mode_listed_with_sections(client: TestClient) -> None:
    modes = client.get("/api/modes").json()
    bead = next(m for m in modes if m["id"] == "bead_analysis")
    names = [p["name"] for p in bead["params"]]
    assert "mm_per_px" in names and "min_diameter_mm" in names and "lens_correction" in names
    sections = {p["section"] for p in bead["params"]}
    assert "Calibration" in sections and "Overlay" in sections
    for name in ("blur", "threshold"):
        spec = next(p for p in bead["params"] if p["name"] == name)
        assert len(spec["help"]) > 40, name
    ru = client.get("/api/modes?lang=ru").json()
    bead_ru = next(m for m in ru if m["id"] == "bead_analysis")
    assert "Калибровка" in {p["section"] for p in bead_ru["params"]}


def test_bead_flow_jpeg(client: TestClient) -> None:
    from synthetic import encode_jpeg, make_bead_image

    img, truth, _ = make_bead_image()
    up = upload(client, encode_jpeg(img), "beads.jpg", "image/jpeg")
    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={
            "mode": "bead_analysis",
            "params": {"mm_per_px": 0.1, "min_diameter_mm": 1.4, "max_diameter_mm": 4.4, "bin_width_mm": 0.5},
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    info = data["info"]
    assert info["count"] == len(truth)
    assert info["dish"] is not None
    report = info["report"]
    assert report["stats"][0]["value"] == str(len(truth))
    assert sum(b["count"] for b in report["histogram"]["bins"]) == len(truth)
    assert len(report["tables"]) == 2
    assert len(report["tables"][1]["rows"]) == len(truth)

    # overlay served as the processed image, original is the input itself
    assert client.get(data["processed_url"]).status_code == 200
    assert data["original_url"].endswith("/files/original")

    # CSV download
    files = {f["name"]: f for f in data["files"]}
    assert "beads.csv" in files
    assert files["beads.csv"]["label"] == "Download CSV"
    assert report["tables"][0]["title"] == "Size groups"
    csv_res = client.get(files["beads.csv"]["url"])
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    assert 'filename="beads_beads.csv"' in csv_res.headers["content-disposition"]
    lines = csv_res.text.strip().splitlines()
    assert lines[0].startswith("index,x_px,y_px,diameter_px,diameter_mm")
    assert len(lines) == len(truth) + 1


def test_bead_flow_png_input_is_served_directly(client: TestClient) -> None:
    from synthetic import encode_png, make_bead_image

    img, truth, _ = make_bead_image(size=600, dish_radius=260)
    up = upload(client, encode_png(img), "beads.png", "image/png")
    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "bead_analysis", "params": {"mm_per_px": 0.1, "min_diameter_mm": 1.4, "max_diameter_mm": 4.4}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["info"]["count"] == len(truth)


def test_bead_validation_errors(client: TestClient) -> None:
    from synthetic import encode_jpeg, make_bead_image

    img, _, _ = make_bead_image(size=400, dish_radius=170)
    up = upload(client, encode_jpeg(img), "beads.jpg", "image/jpeg")
    bad = [
        {"mm_per_px": 0},
        {"min_diameter_mm": 5, "max_diameter_mm": 3},
        {"bin_width_mm": 0},
        {"marker_method": "magic"},
        {"lens_correction": True},  # synthetic image has no EXIF, no profile chosen
    ]
    for params in bad:
        res = client.post(f"/api/uploads/{up['id']}/process", json={"mode": "bead_analysis", "params": params})
        assert res.status_code == 422, (params, res.text)
