"""KerrChow Fit server: serves the page and stands in for the claude.ai runtime it was built for.

- /api/db/*   the page's saved data (check-offs, plan start, weather, Garmin snapshot) in SQLite
- /api/mcp/*  "connector" calls for Strava and Garmin, answered by this server
- /strava/*   one-time Strava sign-in
"""
import base64
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import garmin, jobs, store, strava
from .errors import ToolError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
WEB = Path(__file__).resolve().parent.parent / "web"
AUTH_USER, AUTH_PASS = os.getenv("BASIC_AUTH_USER", ""), os.getenv("BASIC_AUTH_PASSWORD", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
PATH_RE = re.compile(r"^[A-Za-z0-9_\-.~]+(/[A-Za-z0-9_\-.~]+)*$")
SERVERS = {"Strava": strava, "host:Garmin_Connect": garmin}

# Wording in the page that only makes sense on claude.ai, swapped when served from here.
COPY = [
    ("Strava isn't connected to your Claude account.", "Strava isn't connected yet."),
    ("Add it in claude.ai Settings → Connectors, then refresh.", "Connect it at /strava/connect on this server, then refresh."),
    ("Reconnect Strava in claude.ai Settings → Connectors, then refresh.", "Reconnect at /strava/connect on this server, then refresh."),
    (" The Strava connector needs an active Strava subscription.", ""),
    ("AccuWeather forecast for Auckland Central", "Open-Meteo forecast for Auckland Central"),
    ("Garmin Connect isn't reachable here. Live data works in the Claude desktop app on the PC that runs the Garmin server.",
     "Garmin Connect isn't signed in on this server. See the setup guide."),
    ("From Garmin Connect on this PC", "From Garmin Connect"),
]


def _page() -> str:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for old, new in COPY:
        html = html.replace(old, new)
    # The shim must run before the page's own scripts: it provides window.claude.
    return html.replace("<head>", '<head>\n<script src="claude-shim.js"></script>', 1)


@asynccontextmanager
async def lifespan(_app):
    jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="KerrChow Fit", lifespan=lifespan, docs_url=None, redoc_url=None)
PAGE = _page()


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if AUTH_USER and AUTH_PASS and request.url.path != "/healthz":
        ok = False
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, AUTH_USER) and secrets.compare_digest(pw, AUTH_PASS)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="KerrChow Fit"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index():
    return HTMLResponse(PAGE, headers={"Cache-Control": "no-cache"})


# ---------- storage ----------
def _path(p: str) -> str:
    if not PATH_RE.match(p or "") or len(p) > 300 or any(not seg.strip(".") for seg in p.split("/")):
        raise HTTPException(400, "bad path")
    return p


@app.get("/api/db/doc")
def get_doc(path: str):
    data = store.doc_get(_path(path))
    return {"exists": data is not None, "data": data}


@app.put("/api/db/doc")
def put_doc(path: str, data: dict = Body(...)):
    store.doc_set(_path(path), data)
    return {"ok": True}


@app.patch("/api/db/doc")
def patch_doc(path: str, data: dict = Body(...)):
    store.doc_merge(_path(path), data)
    return {"ok": True}


@app.delete("/api/db/doc")
def delete_doc(path: str):
    store.doc_delete(_path(path))
    return {"ok": True}


@app.get("/api/db/collection")
def get_collection(path: str):
    return {"docs": store.collection(_path(path))}


# ---------- "connectors" ----------
@app.get("/api/mcp/servers")
def servers():
    return {"servers": [
        {"server": name, "authStatus": "connected", "tools": [{"name": t, "description": ""} for t in mod.TOOLS]}
        for name, mod in SERVERS.items() if mod.configured()
    ]}


@app.post("/api/mcp/call")
def call(body: dict = Body(...)):
    name, tool = body.get("server"), body.get("tool")
    mod = SERVERS.get(name)
    if not mod or not mod.configured():
        return {"error": {"code": "server_not_connected", "message": f"{name} isn't set up on this server."}}
    if tool not in mod.TOOLS:
        return {"error": {"code": "not_in_manifest", "message": f"{tool} isn't available."}}
    try:
        payload, stored = mod.call(tool, body.get("input") or {}, bool(body.get("refresh")))
    except ToolError as e:
        return {"error": e.as_dict()}
    except Exception as e:  # unexpected: log it, tell the page without crashing the section
        log.exception("%s %s failed", name, tool)
        return {"error": {"code": "upstream_error", "message": str(e)}}
    return {"payload": payload, "storedAt": int(stored * 1000) if stored else None}


@app.get("/api/debug/garmin/{name}")
def garmin_raw(name: str, date: str | None = None):
    """Untranslated Garmin response, for fixing the field mapping if Garmin changes it."""
    try:
        return JSONResponse(garmin.raw(name, date))
    except ToolError as e:
        return JSONResponse({"error": e.as_dict()}, status_code=502)


@app.post("/api/jobs/{name}")
def run_job(name: str):
    """Run a background job now: garmin or weather."""
    from . import weather
    jobs_by_name = {"garmin": garmin.snapshot, "weather": weather.refresh}
    if name not in jobs_by_name:
        raise HTTPException(404)
    jobs_by_name[name]()
    return {"ok": True}


# ---------- Strava sign-in ----------
def _redirect_uri(request: Request) -> str:
    base = PUBLIC_URL or str(request.base_url).rstrip("/")
    return f"{base}/strava/callback"


@app.get("/strava/connect")
def strava_connect(request: Request):
    if not strava.app_configured():
        return PlainTextResponse("Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET on the stack first.", status_code=400)
    return RedirectResponse(strava.auth_url(_redirect_uri(request)))


@app.get("/strava/callback")
def strava_callback(code: str | None = None, error: str | None = None, scope: str = ""):
    if error or not code:
        return PlainTextResponse(f"Strava sign-in was cancelled ({error or 'no code'}).", status_code=400)
    if "activity:read" not in scope:
        return PlainTextResponse("Please allow access to your activities (tick 'View data about your activities'). Go back and try /strava/connect again.", status_code=400)
    strava.exchange_code(code)
    return RedirectResponse("/#stats")


app.mount("/", StaticFiles(directory=WEB), name="web")
