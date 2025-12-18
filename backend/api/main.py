"""
FastAPI application entry point.

Run with: uvicorn api.main:app --reload
"""
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware

# Load environment variables from backend/.env (optional) before other imports that read env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

from api.routes import books, assets, pipeline
from db import init_db
from services.metadata_extractor import register_heif_opener

# Register HEIF/HEIC opener at startup (for iPhone photos)
heif_available = register_heif_opener()


class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    """Middleware to handle Private Network Access preflight requests."""

    async def dispatch(self, request: Request, call_next):
        # Handle preflight for Private Network Access
        if request.method == "OPTIONS":
            response = Response(status_code=204)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Private-Network"] = "true"
            return response

        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response


# Create app
app = FastAPI(
    title="PhotoBook Studio API",
    description="API for generating print-ready photo books",
    version="0.1.0",
)

# Private Network Access middleware (must be before CORS)
app.add_middleware(PrivateNetworkAccessMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for media
media_path = Path("media")
media_path.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# Mount static files for generated maps / caches
data_path = Path("data")
data_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(data_path)), name="static")

# Include routers
app.include_router(books.router, prefix="/books", tags=["books"])
app.include_router(assets.router, prefix="/books/{book_id}/assets", tags=["assets"])
app.include_router(pipeline.router, prefix="/books/{book_id}", tags=["pipeline"])


@app.middleware("http")
async def media_cache_middleware(request: Request, call_next):
    """Add caching headers for media static responses and light ETag/Last-Modified.

    This middleware is simple: for paths under /media we'll set Cache-Control and
    attempt to set Last-Modified and ETag based on the file's mtime and size.
    """
    response = await call_next(request)
    try:
        path = request.url.path
        if path.startswith("/media/") and response.status_code == 200:
            # derive local file path
            rel = path[len("/media/"):]
            file_path = media_path.joinpath(rel)
            if file_path.exists():
                stat = file_path.stat()
                # Cache for one week
                response.headers["Cache-Control"] = "public, max-age=604800, immutable"
                # Last-Modified
                from email.utils import formatdate

                lm = formatdate(stat.st_mtime, usegmt=True)
                response.headers.setdefault("Last-Modified", lm)
                # ETag (weak) based on mtime and size
                etag = f'W/"{stat.st_mtime:.0f}-{stat.st_size}"'
                response.headers.setdefault("ETag", etag)
    except Exception:
        pass
    return response


@app.on_event("startup")
def startup_event():
    """Initialize database tables on startup."""
    init_db()


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "PhotoBook Studio API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
