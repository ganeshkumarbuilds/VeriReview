from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes.repository_review_api import router as repository_review_router

from app.api.routes.auth import router as auth_router
from app.api.routes.execution import router as execution_router
from app.api.routes.fixes import router as fixes_router
from app.api.routes.generation import router as generation_router
from app.api.routes.github_import import router as github_import_router
from app.api.routes.project_files import router as project_files_router
from app.api.routes.projects import router as projects_router
from app.api.routes.reviews import router as reviews_router
from app.services.llm_client import llm_client
from app.workflows.checkpointer import checkpoint_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and release shared application resources."""
    await llm_client.start()
    await checkpoint_manager.start()

    app.state.checkpointer = checkpoint_manager.checkpointer

    try:
        yield
    finally:
        await checkpoint_manager.close()
        await llm_client.close()


app = FastAPI(
    title="VeriReview API",
    description="Agentic AI Software Engineering Platform",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API routers
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(project_files_router)
app.include_router(github_import_router)
app.include_router(execution_router)
app.include_router(generation_router)
app.include_router(reviews_router)
app.include_router(fixes_router)
app.include_router(repository_review_router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to VeriReview",
        "status": "running",
        "platform": "Agentic AI Software Engineering Platform",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "VeriReview Backend",
    }
