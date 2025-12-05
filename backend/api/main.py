"""
FastAPI application entry point.

Run with: uvicorn api.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.routes import books, assets, pipeline
from services.metadata_extractor import register_heif_opener

# Register HEIF/HEIC opener at startup (for iPhone photos)
heif_available = register_heif_opener()

# Create app
app = FastAPI(
    title="PhotoBook Studio API",
    description="API for generating print-ready photo books",
    version="0.1.0",
)

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

# Include routers
app.include_router(books.router, prefix="/books", tags=["books"])
app.include_router(assets.router, prefix="/books/{book_id}/assets", tags=["assets"])
app.include_router(pipeline.router, prefix="/books/{book_id}", tags=["pipeline"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "PhotoBook Studio API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
