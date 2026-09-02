from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.conflicts.router import router as conflicts_router
from app.consume.router import (
    context_router,
    explorer_router,
    graph_router,
    projections_router,
    search_router,
)
from app.discovery.router import router as discovery_router
from app.health import router as health_router
from app.kernel.errors import KernelError
from app.knowledge.router import router as knowledge_router
from app.metrics.router import router as metrics_router
from app.notifications.router import router as notifications_router
from app.questions.router import router as questions_router
from app.reviews.router import router as reviews_router
from app.sources.router import router as sources_router

app = FastAPI(title="Business Semantic Platform", version="0.1.0")


@app.exception_handler(KernelError)
def kernel_error_handler(_request: Request, exc: KernelError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(knowledge_router)
app.include_router(sources_router)
app.include_router(reviews_router)
app.include_router(notifications_router)
app.include_router(discovery_router)
app.include_router(conflicts_router)
app.include_router(questions_router)
app.include_router(search_router)
app.include_router(explorer_router)
app.include_router(context_router)
app.include_router(projections_router)
app.include_router(graph_router)
app.include_router(metrics_router)
