# KinGuard frontend

The React and Vite app for people and caregivers. It calls the FastAPI service in the sibling [`backend/`](../backend/); the routes and roles are described in its [API contract](../backend/API.md).

## Run locally

Start the backend first by following the [backend setup](../backend/README.md). From `frontend/`:

```powershell
npm.cmd install
Copy-Item .env.example .env.local
# Set VITE_CLERK_PUBLISHABLE_KEY in .env.local to your Clerk publishable key.
npm.cmd run dev
```

Open the local URL printed by Vite. Its dev server proxies `/api` to `http://127.0.0.1:8000`, so `VITE_API_URL` and backend CORS settings are unnecessary for this local setup. For a frontend served separately, set `VITE_API_URL` to the backend origin and add the frontend origin to `CORS_ORIGINS` in `backend/.env`.

Keep `CLERK_SECRET_KEY` in `backend/.env`; the frontend uses only the publishable key. The product app requires a Clerk session and the backend's corresponding secret key.

## Checks

```powershell
npm.cmd run build
npm.cmd run lint
```
