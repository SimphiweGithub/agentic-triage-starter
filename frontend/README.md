# Scam Stop frontend

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

**Local demo mode.** Without a publishable key in `.env.local`, the dashboard runs without sign-in (`src/auth.tsx`) and shows "Local demo: no sign-in". That only works against a backend with `KINGUARD_DEV_OPEN=1`, which skips sign-in too. Add the key and Clerk is used exactly as before.

After `npm.cmd run build`, the backend serves the dashboard itself at `http://localhost:8000/`; the old developer console moved to `/console`.

## Checks

```powershell
npm.cmd run build
npm.cmd run lint
```

## Calls and the care circle

The Calls and Care circle tabs and the phone's call alerts expect these routes, which the backend does not serve yet. Until it does, the screens say the call monitor is not on and show only the person and you in the circle.

| Route | Returns or takes |
|---|---|
| `GET /people/{id}/calls` | `[{call_id, number, at, seconds, in_contacts, contact_name, tips_shown, answer}]`; `answer` is `known`, `asked_code`, `told_kin` or `null` |
| `POST /people/{id}/calls/{call_id}/answer` | `{answer}`, sent by the paired phone with `X-Device-Key` |
| `GET /people/{id}/circle` | `[{id, name, relation, role, status, you}]`; `role` is `protected`, `next_of_kin`, `caregiver` or `helper` |
| `POST /people/{id}/circle/invites` | `{name, role}` → `{token, role, name, expires_at}` |

The phone app also expects a native `CallMonitor` Capacitor plugin (`src/phone/call-monitor.ts` describes it): it sees only that a call happened, the number, its length and whether it is a contact, reports unknown calls to the server, and opens the app on the call scams screen from its notification.

To preview the phone screens in a desktop browser during development, open the dev server with `?phone`.
