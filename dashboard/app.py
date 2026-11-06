"""Atlas Ops dashboard: FastAPI app.

Serves the six server-rendered pages, mounts /static, and includes each
api/<page>.py router. Run with ./run.sh (uvicorn on port 4500).
"""

import importlib
import logging
import os
import traceback
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("atlas")
# Cache-busting stamp for /static links; changes on every restart (every deploy).
ASSET_V = str(int(__import__("time").time()))

PAGES = [
    # route name, path, nav label, title, one-line description
    ("home", "/", "Home", "Overview", "Headline numbers and where to go next."),
    ("reporting", "/reporting", "Reporting", "Reporting",
     "Cost per trial and paid conversion by campaign, daily spend and rolling 3-day cost per trial, PostHog truth vs platform claims."),
    ("campaigns", "/campaigns", "Campaigns", "Campaigns",
     "Every campaign's spend, budget, pacing and cost per trial, with pause, budget, ad set and negative-keyword controls."),
    ("management", "/management", "Management", "Management",
     "Everything that needs action, the test scoreboard and testing schedule, today's checklist and tracking status."),
    ("planning", "/planning", "Plan & Adapt", "Plan & Adapt",
     "Pull account state, compare it to the 30-day plan, draft API changes from a brief, review the diff, publish by hand."),
    ("media", "/media", "Media", "Media library",
     "Numbered image, video and HTML5 assets: creative requests, ready for review, approved, active."),
    ("calendar", "/calendar", "Calendar", "Content and testing calendar",
     "The launch schedule month by month: content items and tests by day."),
    ("chat", "/chat", "Quick Chat", "Quick chat",
     "Ask about the plan, the latest account state and Search Atlas offerings."),
]
# Pinned to the bottom of the sidebar, apart from the page list (templates/base.html).
LINK_PAGE = ("link_accounts", "/link-accounts", "Link Accounts", "Link Accounts",
             "Connect Google Ads, Meta, LinkedIn, TikTok and X; switch between sample and live data.")
API_PAGES = ["spend", "campaigns", "reporting", "management", "planning", "media", "calendar", "chat", "accounts"]

app = FastAPI(title="Atlas Ops", version="1.0", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
# Same files under a per-deploy path: Cloudflare ignores query strings, so a new path is the only reliable cache key.
app.mount("/s/%s" % ASSET_V, StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static_v")


@app.middleware("http")
async def _no_edge_cache_for_code(request, call_next):
    # Scripts and styles change on every deploy; stop Cloudflare's edge from serving stale copies.
    # Browsers still revalidate cheaply with the ETag (304). Media and images keep normal caching.
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/static/js/", "/static/css/")) or not path.startswith(("/static/", "/s/")):
        response.headers["Cache-Control"] = "no-cache"
    return response
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _data_mode():
    # type: () -> str
    try:
        import accounts
        return accounts.get_data_mode()
    except Exception:  # never let the secrets dir break page rendering
        return "sample"


def _live_available():
    # type: () -> bool
    try:
        import accounts
        return accounts.any_tested()
    except Exception:
        return False


templates.env.globals["data_mode"] = _data_mode
templates.env.globals["live_available"] = _live_available


# ------------------------------------------------------------------ error map

@app.exception_handler(store.NotFound)
def _not_found(request, exc):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)


@app.exception_handler(store.BadInput)
def _bad_input(request, exc):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.exception_handler(RequestValidationError)
def _validation(request, exc):
    errs = exc.errors()
    msg = "; ".join("%s: %s" % (".".join(str(x) for x in e.get("loc", [])[1:]) or "body", e.get("msg"))
                    for e in errs) or "invalid request"
    return JSONResponse({"ok": False, "error": msg, "detail": errs}, status_code=400)


# ------------------------------------------------------------- page routers

ROUTER_ERRORS = {}  # type: Dict[str, str]

for _name in API_PAGES:
    try:
        _mod = importlib.import_module("api.%s" % _name)
        _router = getattr(_mod, "router", None)
        if _router is not None:
            app.include_router(_router)
        else:
            ROUTER_ERRORS[_name] = "module has no `router`"
    except Exception:  # a broken page module must not take the other pages down
        ROUTER_ERRORS[_name] = traceback.format_exc(limit=3)
        log.error("failed to load api.%s:\n%s", _name, ROUTER_ERRORS[_name])


@app.get("/api/health")
def health():
    # type: () -> Dict[str, Any]
    return {"ok": True, "today": store.today(), "adapter": store.get_state()["meta"].get("adapter", "local"),
            "routers": {n: ("error" if n in ROUTER_ERRORS else "ok") for n in API_PAGES}}


# --------------------------------------------------------------------- pages

def _nav():
    # type: () -> List[Dict[str, str]]
    return [{"name": n, "path": p, "label": l, "title": t, "description": d} for (n, p, l, t, d) in PAGES]


def _context(request, page, **extra):
    # type: (Request, str, Any) -> Dict[str, Any]
    title = [p[3] for p in PAGES + [LINK_PAGE] if p[0] == page][0]
    ctx = {"request": request, "page": page, "title": title, "nav": _nav(),
           "link_nav": {"name": LINK_PAGE[0], "path": LINK_PAGE[1], "label": LINK_PAGE[2]},
           "today": store.today(), "meta": store.get_state()["meta"], "store": store, "asset_v": ASSET_V}
    ctx.update(extra)
    return ctx


def _render(request, template, page, **extra):
    return templates.TemplateResponse(request, template, _context(request, page, **extra))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    p_all = store.pacing()
    w7 = store.window_totals(None, 7)
    mtd = store.month_to_date()
    kpis = {
        "mtd_spend": p_all["month_to_date_spend"],
        "monthly_budget": p_all["monthly_budget"],
        "trials_mtd": mtd["trials"],
        "cpt_mtd": mtd["cost_per_trial"],
        "cpt_7d": w7["cost_per_trial"],
        "trials_7d": w7["trials"],
        "pace_pct": p_all["pace_pct"],
        "projected": p_all["projected_month_end"],
        "days_elapsed": p_all["days_elapsed"],
        "days_in_month": p_all["days_in_month"],
        "platforms": {pl: store.pacing(pl) for pl in ("google", "meta")},
    }
    return _render(request, "home.html", "home", kpis=kpis)


def _page_route(name, path):
    def view(request: Request):
        return _render(request, "%s.html" % name, name)
    view.__name__ = "page_%s" % name
    app.add_api_route(path, view, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)


for _n, _p, _l, _t, _d in PAGES:
    if _n != "home":
        _page_route(_n, _p)


@app.get("/link-accounts", response_class=HTMLResponse, include_in_schema=False)
def page_link_accounts(request: Request):
    return _render(request, "link_accounts.html", "link_accounts")


@app.get("/spend", include_in_schema=False)
def spend_moved():
    # The Spend page became Campaigns (2026-11-05).
    return RedirectResponse("/campaigns", status_code=301)
