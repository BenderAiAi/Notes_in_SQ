from notes_app.terminations.web import create_app
from notes_app.web import create_app as create_main_app


def _client():
    return create_app({"TESTING": True}).test_client()


def test_settings_put_and_get(temp_data):
    client = _client()

    bad = client.put("/api/settings", json={"source_dir": str(temp_data / "missing"), "output_dir": ""})
    assert bad.status_code == 400

    source = temp_data / "src"
    source.mkdir()
    output = temp_data / "out"
    ok = client.put("/api/settings", json={"source_dir": str(source), "output_dir": str(output)})
    assert ok.status_code == 200
    assert ok.get_json()["source_dir"] == str(source)

    assert client.get("/api/settings").get_json()["source_dir"] == str(source)


def test_index_renders(temp_data):
    client = _client()
    response = client.get("/")
    assert response.status_code == 200
    assert "Расторжения Dubai/TRS".encode() in response.data


def test_api_is_mounted_in_main_noteflow_app(temp_data):
    client = create_main_app({"TESTING": True}).test_client()
    response = client.get("/terminations/api/settings")
    assert response.status_code == 200
    assert response.get_json() == {"source_dir": "", "output_dir": ""}


def test_history_empty(temp_data):
    client = _client()
    data = client.get("/api/history").get_json()
    assert data["items"] == []
    assert data["summary"]["total"] == 0


def test_scan_without_source_returns_400(temp_data):
    client = _client()
    response = client.post("/api/reports/scan", json={})
    assert response.status_code == 400


def test_analyze_rejects_file_outside_source(temp_data):
    client = _client()
    source = temp_data / "src"
    source.mkdir()
    client.put("/api/settings", json={"source_dir": str(source), "output_dir": str(temp_data / "out")})

    response = client.post("/api/reports/analyze", json={"path": str(temp_data / "elsewhere.xlsx")})
    assert response.status_code == 400
