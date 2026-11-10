import base64
import importlib

import pytest
from fastapi.testclient import TestClient


def client(monkeypatch, **env):
    for k in ("BASIC_AUTH_USER", "BASIC_AUTH_PASSWORD", "ALLOW_NO_LOGIN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app import main
    importlib.reload(main)
    return TestClient(main.app, follow_redirects=False)   # no lifespan: background jobs stay off


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_refuses_to_run_without_a_login(monkeypatch):
    c = client(monkeypatch)
    for path in ("/", "/api/db/doc?path=garmin/latest", "/api/debug/garmin/status"):
        r = c.get(path)
        assert r.status_code == 503 and "BASIC_AUTH_USER" in r.text
    assert c.put("/api/db/doc?path=progress/w1", json={"x": 1}).status_code == 503
    assert c.get("/healthz").json() == {"ok": True}


def test_login_is_required_when_set(monkeypatch):
    c = client(monkeypatch, BASIC_AUTH_USER="adam", BASIC_AUTH_PASSWORD="s3cret")
    assert c.get("/").status_code == 401
    assert c.get("/", headers=basic("adam", "wrong")).status_code == 401
    assert c.get("/", headers={"Authorization": "Basic not-base64!"}).status_code == 401
    r = c.get("/", headers=basic("adam", "s3cret"))
    assert r.status_code == 200 and "claude-shim.js" in r.text and "KerrChow" in r.text


def test_open_mode_must_be_asked_for(monkeypatch):
    c = client(monkeypatch, ALLOW_NO_LOGIN="true")
    assert c.get("/").status_code == 200
    assert c.put("/api/db/doc?path=progress/w3", json={"days": {"tue": True}}).json() == {"ok": True}
    assert c.get("/api/db/doc?path=progress/w3").json() == {"exists": True, "data": {"days": {"tue": True}}}
    assert c.get("/api/db/doc?path=../etc/passwd").status_code == 400
    assert c.get("/api/mcp/servers").json() == {"servers": []}
    assert c.post("/api/mcp/call", json={"server": "Strava", "tool": "list_activities"}).json()["error"]["code"] == "server_not_connected"
    assert c.post("/api/mcp/call", json={"server": "host:Garmin_Connect", "tool": "get_user_summary"}).json()["error"]["code"] == "server_not_connected"
    assert c.post("/api/garmin/get_user_summary", json={}).json()["error"]["code"] == "server_not_connected"


def test_credentials_are_saved_but_never_sent_back(monkeypatch):
    from app import garmin, store
    c = client(monkeypatch, ALLOW_NO_LOGIN="true")
    monkeypatch.setattr(garmin, "_exchange", lambda key: {"token": "t", "expires_at": 9e9})
    st = c.get("/api/integrations").json()
    assert st["garmin"] == {"configured": False, "source": None} and st["strava"]["app_configured"] is False

    st = c.put("/api/integrations/garmin", json={"api_key": "gk-123"}).json()
    assert st["garmin"] == {"configured": True, "source": "saved"} and "gk-123" not in str(st)
    assert c.put("/api/integrations/garmin", json={"api_key": " "}).status_code == 400

    assert c.put("/api/integrations/strava", json={"client_id": "abc", "client_secret": "s"}).status_code == 400
    store.kv_put("strava_tokens", {"access_token": "a", "refresh_token": "r", "expires_at": 0})
    st = c.put("/api/integrations/strava", json={"client_id": "123", "client_secret": "shh"}).json()
    assert st["strava"] == {"app_configured": True, "source": "saved", "connected": False}  # a new app drops old tokens
    assert "shh" not in str(st)
    assert c.get("/strava/connect").status_code == 307

    assert c.delete("/api/integrations/garmin").json()["garmin"]["configured"] is False
    assert c.delete("/api/integrations/strava").json()["strava"]["app_configured"] is False


def test_every_wording_swap_still_matches_the_page(monkeypatch, caplog):
    client(monkeypatch, ALLOW_NO_LOGIN="true")
    assert not [r for r in caplog.records if "wording not found" in r.getMessage()]


def test_strava_sign_in_needs_a_matching_state(monkeypatch):
    c = client(monkeypatch, ALLOW_NO_LOGIN="true")
    r = c.get("/strava/callback?code=abc&scope=read,activity:read_all&state=forged")
    assert r.status_code == 400 and "didn't start here" in r.text
    assert c.get("/strava/callback?code=abc&scope=read,activity:read_all").status_code == 400
