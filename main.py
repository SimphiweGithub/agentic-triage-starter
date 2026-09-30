from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Agentic Triage Starter", version="0.1.0")
app.include_router(router, prefix="/api")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "static" / "index.html")
