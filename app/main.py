from pathlib import Path
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# .env loading logic
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

from app.api.routes import auth, admin, chat, citations, explore, feedback, papers, reports, search, synthesis, user

# Warm-up: kick off embedding model load in the background. The server
# accepts requests immediately; the first synthesis request after boot will
# wait on the same get_model() call if warmup hasn't finished, which is
# guarded by a lock inside embeddings.py so we never double-load.
@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    log = logging.getLogger(__name__)
    loop = asyncio.get_event_loop()

    def _bg_warmup():
        try:
            from app.services.synthesis.embeddings import warm_up_model
            warm_up_model()
        except Exception as exc:
            log.warning("Embedding warm-up failed: %s", exc)

    loop.run_in_executor(None, _bg_warmup)
    log.info("Embedding warm-up scheduled in background; server is ready.")
    yield

app = FastAPI(
    title="Research Agent API",
    lifespan=lifespan,
)
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR
INDEX_FILE = FRONTEND_DIR / "html" / "index.html"
NODE_MODULES_DIR = BASE_DIR / "node_modules"

# Updated Middleware with Bypass for Localhost
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    
    response = await call_next(request)
    path = request.url.path

    if path in {"/", "/index.html"} or path == "/workspace" or path.startswith("/workspace/") or path.startswith("/js/") or path.startswith("/css/") or path.startswith("/html/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, tags=["Auth"])
app.include_router(papers.router, tags=["Papers"])
app.include_router(reports.router, tags=["Reports"])
app.include_router(search.router, tags=["Search"])
app.include_router(synthesis.router)
app.include_router(citations.router)
app.include_router(admin.router)
app.include_router(user.router)
app.include_router(user.users_router)
app.include_router(chat.router)
app.include_router(explore.router)
app.include_router(feedback.router)


@app.on_event("startup")
async def _bootstrap_db() -> None:
    import logging

    from app.core.config import settings
    from app.db.session import init_indexes, ping
    from app.services.citations.cache import ensure_indexes

    log = logging.getLogger(__name__)
    if settings.AUTH_DEV_BYPASS:
        log.warning(
            "AUTH_DEV_BYPASS=1 — unauthenticated requests resolve to a synthetic admin. "
            "Set AUTH_DEV_BYPASS=0 in any non-local environment."
        )
    if await ping():
        log.info("MongoDB reachable; bootstrapping indexes")
    else:
        log.warning("MongoDB unreachable at startup; index creation will be skipped")
        return

    try:
        await init_indexes()
    except Exception:
        log.exception("Failed to bootstrap core indexes")

    try:
        await ensure_indexes()
    except Exception:
        log.exception("Failed to bootstrap citation_cache indexes")


@app.on_event("shutdown")
async def _shutdown_db() -> None:
    from app.db.session import close_db

    await close_db()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")
app.mount("/html", StaticFiles(directory=FRONTEND_DIR / "html"), name="frontend-html")

if NODE_MODULES_DIR.exists():
    app.mount("/vendor", StaticFiles(directory=NODE_MODULES_DIR), name="vendor-node-modules")

# Custom OpenAPI
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Research Agent API",
        version="1.0.0",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(INDEX_FILE)


@app.get("/index.html", include_in_schema=False)
def frontend_index():
    return FileResponse(INDEX_FILE)


@app.get("/workspace", include_in_schema=False)
def frontend_workspace():
    return FileResponse(INDEX_FILE)


@app.get("/workspace/search", include_in_schema=False)
def frontend_workspace_search():
    return FileResponse(INDEX_FILE)


# Catch-all so every client-side `/workspace/...` route serves the SPA shell.
# Client-side routing (syncFromLocation in appStore.js) takes over from there.
@app.get("/workspace/{subpath:path}", include_in_schema=False)
def frontend_workspace_subpath(subpath: str):
    return FileResponse(INDEX_FILE)


@app.get("/synthesis/share/{report_id}", include_in_schema=False)
def frontend_share_link(report_id: str):
    return FileResponse(INDEX_FILE)


ADMIN_PAGE = FRONTEND_DIR / "html" / "admin.html"


@app.get("/admin-panel", include_in_schema=False)
def frontend_admin_panel():
    if not ADMIN_PAGE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Admin page not available")
    return FileResponse(ADMIN_PAGE)


@app.get("/health", tags=["Health"])
def home():
    return {"message": "Research Agent API running"}
