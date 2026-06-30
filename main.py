import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from api import router
from db import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zonasisekolahjawabarat.netlify.app"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Role", "X-User-Id"],
)

# ── TEMPORARY: debug handler — REMOVE after the bug is found ──────
# Surfaces the real exception + traceback in the JSON response instead
# of a bare "Internal Server Error", and (as a bonus) keeps CORS headers
# intact on error responses since this runs inside the CORS middleware.
@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        },
    )

app.include_router(router)
