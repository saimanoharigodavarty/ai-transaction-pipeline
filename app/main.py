from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routes.jobs import router as jobs_router

# Automatically create database tables if they do not exist
# Note: In a production system, we would typically use alembic for migrations.
Base.metadata.create_all(bind=engine)

# Initialize FastAPI application
app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    description="Asynchronous CSV parser, outlier & location anomaly detector, and Gemini category classifier.",
    version="1.0.0"
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows requests from any origin/port (e.g. React local dev port)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all standard methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all custom headers
)

# Include routes
app.include_router(jobs_router)

@app.get("/")
def read_root():
    """
    Root endpoint to verify service health.
    """
    return {
        "status": "healthy",
        "message": "AI-Powered Transaction Processing Pipeline API is running."
    }
