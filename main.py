from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import router
from db import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zonasisekolahjabar.netlify.app"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Role", "X-User-Id"],
)

app.include_router(router)
