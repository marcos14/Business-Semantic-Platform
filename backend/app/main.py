from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.health import router as health_router
from app.kernel.errors import KernelError
from app.knowledge.router import router as knowledge_router
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
