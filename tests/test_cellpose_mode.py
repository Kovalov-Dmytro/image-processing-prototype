"""End-to-end test of the Cellpose mode. Skipped when cellpose is not installed.

Runs the real cyto3 network on the CPU over a small synthetic image, so it takes a
few seconds (plus numba compilation on a cold cache).
"""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from synthetic import encode_jpeg, make_bead_image

cellpose_available = importlib.util.find_spec("cellpose") is not None
pytestmark = pytest.mark.skipif(not cellpose_available, reason="cellpose is not installed")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_cellpose_mode_listed(client: TestClient) -> None:
    modes = {m["id"]: m for m in client.get("/api/modes").json()}
    assert "cellpose_beads" in modes
    names = [p["name"] for p in modes["cellpose_beads"]["params"]]
    for expected in ("mm_per_px", "model_type", "flow_threshold", "max_fit_error", "lens_correction"):
        assert expected in names
    assert client.get("/api/health").json()["cellpose"] is True


def test_cellpose_flow_counts_and_sizes(client: TestClient) -> None:
    img, truth, _ = make_bead_image(size=600, dish_radius=260, spacing=50, touching_pairs=2)
    up = client.post("/api/uploads", files={"file": ("beads.jpg", encode_jpeg(img), "image/jpeg")}).json()
    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={
            "mode": "cellpose_beads",
            "params": {"mm_per_px": 0.1, "min_diameter_mm": 1.4, "max_diameter_mm": 4.4, "bin_width_mm": 0.5},
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    info = data["info"]
    # A neural network is not exact: allow a small miss/extra margin.
    assert abs(info["count"] - len(truth)) <= max(2, round(0.05 * len(truth))), (info["count"], len(truth))
    rows = info["report"]["tables"][1]["rows"]
    diameters_px = [r[3] for r in rows]
    assert min(diameters_px) > 14 and max(diameters_px) < 36
    assert any(s["label"] == "Cellpose masks" for s in info["report"]["stats"])
    assert "cellpose cyto3" in data["log"]
    assert client.get(data["processed_url"]).status_code == 200
    csv_text = client.get(data["files"][0]["url"]).text
    assert csv_text.splitlines()[0].endswith("fit_error")


def test_cellpose_validation(client: TestClient) -> None:
    img, _, _ = make_bead_image(size=400, dish_radius=170)
    up = client.post("/api/uploads", files={"file": ("beads.jpg", encode_jpeg(img), "image/jpeg")}).json()
    res = client.post(
        f"/api/uploads/{up['id']}/process",
        json={"mode": "cellpose_beads", "params": {"model_type": "unknown"}},
    )
    assert res.status_code == 422
