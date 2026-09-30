# KinGuard

This repository has two applications:

- [`backend/`](backend/) contains the FastAPI service, developer console, tests, samples, and documentation. See its [README](backend/README.md).
- [`frontend/`](frontend/) contains the React and Vite product app. See its [README](frontend/README.md). It uses the [backend API contract](backend/API.md).

Start the backend from `backend/` on port 8000, then start the frontend from `frontend/` on Vite's local development port. Vite proxies `/api` to the backend. Each app has its own environment file; follow the READMEs for setup.
