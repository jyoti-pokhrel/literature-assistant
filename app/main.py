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

from app.api.routes import auth, citations, papers, reports, search, synthesis

# Warm-up: pre-load embedding model 
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    try:
        from app.services.synthesis.embeddings import warm_up_model
        await loop.run_in_executor(None, warm_up_model)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Embedding warm-up failed: %s", exc)
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

    if path in {"/", "/index.html", "/workspace", "/workspace/search"} or path.startswith("/js/") or path.startswith("/css/"):
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


@app.on_event("startup")
async def _bootstrap_citation_indexes() -> None:
    from app.services.citations.cache import ensure_indexes

    try:
        await ensure_indexes()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to bootstrap citation_cache indexes")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")

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


@app.get("/synthesis/share/{report_id}", include_in_schema=False)
def frontend_share_link(report_id: str):
    return FileResponse(INDEX_FILE)


@app.get("/health", tags=["Health"])
def home():
    return {"message": "Research Agent API running"}
