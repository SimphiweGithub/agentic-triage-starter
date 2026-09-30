import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="KinGuard API", version="0.2.0",
              description="Backend for KinGuard. See API.md for the contract and /docs for interactive documentation.")

# Off by default: the API then answers only same-origin pages. A separately served front end
# lists its own address in CORS_ORIGINS, for example http://localhost:5173 (comma separated).
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

app.include_router(router, prefix="/api")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def console():
    """A plain developer console for watching the engine. The product front end is built separately."""
    return FileResponse(ROOT / "static" / "index.html")
