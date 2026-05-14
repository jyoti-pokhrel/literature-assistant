from pathlib import Path
import asyncio
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import logging

from app.api.routes import auth, papers, synthesis, search, admin, user, chat
from app.db.session import connect_to_mongo, close_mongo_connection, create_indexes
from app.core.config import settings
from app.core.http import get_http_client, close_http_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Research Agent API",
)
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR
INDEX_FILE = FRONTEND_DIR / "html" / "index.html"
NODE_MODULES_DIR = BASE_DIR / "node_modules"

# CORS setup - strictly from .env
allowed_origins = [settings.FRONTEND_URL] if settings.FRONTEND_URL else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add ProxyHeadersMiddleware to handle ngrok/proxy headers
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Rate Limiting Middleware
import time
from collections import defaultdict

# rate_limit_store[identifier] = [timestamp1, timestamp2, ...]
rate_limit_store = defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Public assets don't count towards rate limit
    path = request.url.path
    if path.startswith(("/static", "/css", "/js", "/html", "/favicon.ico")):
        return await call_next(request)
        
    # Use client IP as identifier for non-auth, or username if available
    # For now, IP is safest for middleware level
    client_ip = request.client.host
    now = time.time()
    
    # Filter out timestamps older than 60 seconds
    rate_limit_store[client_ip] = [t for t in rate_limit_store[client_ip] if now - t < 60]
    
    if len(rate_limit_store[client_ip]) >= 60:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too Many Requests. Limit: 60 requests per minute."}
        )
        
    rate_limit_store[client_ip].append(now)
    return await call_next(request)

# Force HTTPS for scope if x-forwarded-proto is https (for accurate URL generation)
@app.middleware("http")
async def force_https_middleware(request: Request, call_next):
    if request.headers.get("x-forwarded-proto") == "https":
        request.scope["scheme"] = "https"
    return await call_next(request)

# Middleware with Bypass for Localhost caching
@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path

    if path in {"/", "/index.html", "/workspace", "/workspace/search"} or path.startswith("/js/") or path.startswith("/css/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

# Include routers FIRST so API endpoints take precedence
app.include_router(auth.router)
app.include_router(papers.router)
app.include_router(synthesis.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(user.router)
app.include_router(chat.router)

# Mount static files correctly
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")
# HTML route for accessing auth pages via /html/login.html if needed
app.mount("/html", StaticFiles(directory=FRONTEND_DIR / "html"), name="frontend-html")

if NODE_MODULES_DIR.exists():
    app.mount("/vendor", StaticFiles(directory=NODE_MODULES_DIR), name="vendor-node-modules")

@app.on_event("startup")
async def startup_db_client():
    await connect_to_mongo()
    await create_indexes()

@app.on_event("startup")
async def startup_services():
    # Initialize shared HTTP client
    get_http_client()
    
    # Background preloading
    asyncio.create_task(preload_assets())

async def preload_assets():
    """Background task to preload models and establish initial connections."""
    logger.info("Starting background asset preloading...")
    try:
        # Preload embedding model (SentenceTransformer)
        from app.services.synthesis.embeddings import get_model
        from app.core.config import settings
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, get_model, os.getenv("EMBEDDING_MODEL"))
        logger.info("Embedding model preloaded successfully.")
        
        # Pre-connect to external APIs
        client = get_http_client()
        urls = [
            "https://export.arxiv.org/api/query",
            "https://api.openalex.org/works",
            "https://api.semanticscholar.org/graph/v1/paper/search"
        ]
        for url in urls:
            try:
                await client.options(url, timeout=2.0)
            except Exception:
                pass
        logger.info("Initial API pre-connections attempted.")
    except Exception as exc:
        logger.warning("Background preloading encountered an issue: %s", exc)

@app.on_event("shutdown")
async def shutdown_db_client():
    await close_mongo_connection()
    await close_http_client()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )

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

ADMIN_PAGE = FRONTEND_DIR / "html" / "admin.html"

@app.get("/admin-panel", include_in_schema=False)
def frontend_admin_panel():
    return FileResponse(ADMIN_PAGE)

@app.get("/health", tags=["Health"])
def home():
    return {"message": "Research Agent API running"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi import Response
    return Response(status_code=204)