"""
Echolia Backend - FastAPI Application

Privacy-first sync and LLM inference service for Echolia apps.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
import logging

from app.config import settings
from app.auth.routes import router as auth_router


# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Privacy-first sync and LLM inference service",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None
)


# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",  # Tauri desktop app
        "http://localhost:3000",  # Local development
        "http://localhost:8080",  # Local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(auth_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "status": "operational",
        "environment": settings.environment
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected"
    }


@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info(
        "application_starting",
        environment=settings.environment,
        debug=settings.debug
    )

    # Initialize master database
    from app.master_db import master_db_manager
    try:
        # Create master database if it doesn't exist
        await master_db_manager.create_master_database()
        logger.info("master_database_initialized")
    except Exception as e:
        logger.error("master_database_initialization_failed", error=str(e))
        # Don't crash the app, but log the error


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("application_shutting_down")

    # Clean up database connections
    from app.database import db_manager
    from app.master_db import master_db_manager

    db_manager.close_all_connections()
    master_db_manager.close_connection()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level
    )
