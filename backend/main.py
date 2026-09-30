import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.gmail import router as gmail_router, start_watching
from api.mailbox import start_polling
from api.routes import router, take_in_email

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Scam Stop API", version="0.2.0",
              description="Backend for Scam Stop. See API.md for the contract and /docs for interactive documentation.")

# Off by default: the API then answers only same-origin pages. A separately served front end
# lists its own address in CORS_ORIGINS, for example http://localhost:5173 (comma separated).
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])

app.include_router(router, prefix="/api")
app.include_router(gmail_router, prefix="/api")  # needs CLERK_SECRET_KEY; answers 503 without it
if os.getenv("GMAIL_WATCH_USER") and os.getenv("CLERK_SECRET_KEY"):
    start_watching(os.environ["GMAIL_WATCH_USER"])  # resume watching after a restart without anyone signing in again
start_polling(take_in_email)  # live mailbox; does nothing unless IMAP_HOST is set
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def console():
    """A plain developer console for watching the engine. The product front end is built separately."""
    return FileResponse(ROOT / "static" / "index.html")
