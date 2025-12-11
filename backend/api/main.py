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
