import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.gmail_block import register as register_gmail_blocking
from api.mailbox import start_polling
from api.people import router as people_router
from api.auth import dev_open
from api.routes import open_router, person_router, router
from api.scanner import forwarded_handler, note_forwarded, start_scanning
from api.store import get_store

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Scam Stop API", version="0.2.0",
              description="Backend for Scam Stop. See API.md for the contract and /docs for interactive documentation.")

# Off by default: the API then answers only same-origin pages. A separately served front end
# lists its own address in CORS_ORIGINS, for example http://localhost:5173 (comma separated).
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization", "X-Device-Key"])

app.include_router(open_router, prefix="/api")      # /api/health
app.include_router(people_router, prefix="/api")    # /api/me, /api/people, /api/invites
for each in (person_router, router):
    app.include_router(each, prefix="/api/people/{person_id}")  # everything about one person names them in the address
    if dev_open():  # the plain console cannot name a person, so in development mode the same routes also answer without one
        app.include_router(each, prefix="/api", include_in_schema=False)

store = get_store()
first = store.first_person()
if os.getenv("IMAP_HOST") and first:
    store.ensure_forwarded(first["id"], os.getenv("IMAP_USER", "Forwarded inbox"))  # the server's one IMAP mailbox belongs to the first person
start_polling(forwarded_handler(store), lambda error: note_forwarded(store, error))  # the server's own mailbox; needs IMAP_HOST
start_scanning(store)  # each person's connected Gmail; needs CLERK_SECRET_KEY
register_gmail_blocking()  # marking an email scammer also blocks them in the person's Gmail, where allowed
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/console", include_in_schema=False)
def console():
    """A plain developer console for watching the engine. The product front end is in frontend/."""
    return FileResponse(ROOT / "static" / "index.html")


# The Scam Stop dashboard, once built with `npm run build` in frontend/, is served at / from the same origin.
# Mounted last, so every /api route above is matched first. Without a build, / sends you to the console.
DASHBOARD = ROOT.parent / "frontend" / "dist"
if (DASHBOARD / "index.html").exists():
    app.mount("/", StaticFiles(directory=DASHBOARD, html=True), name="dashboard")
else:
    @app.get("/", include_in_schema=False)
    def no_dashboard():
        return RedirectResponse("/console")
