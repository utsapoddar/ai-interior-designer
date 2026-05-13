from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from chat.routes.catalog import router as catalog_router
from chat.routes.health import router as health_router
from chat.routes.plans import router as plans_router
from chat.routes.scans import router as scans_router

app = FastAPI(title="Room Designer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(scans_router)
app.include_router(plans_router)
app.include_router(catalog_router)
