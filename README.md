# AI Avlokan Quiz

React/Vite participant and organizer clients with a FastAPI/SQLAlchemy backend. Local development defaults to SQLite; public deployments should use PostgreSQL and separate hosted frontend/API services.

## Local development

Backend, in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Set a private `ADMIN_PASSWORD` in `backend/.env`. Local development uses SQLite and defaults to `http://localhost:5173` for the frontend.

Frontend, in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend derives its local API address from the page host and uses port 8000.

## Public deployment

### Recommended layout

- Vercel: static React/Vite frontend. `frontend/vercel.json` rewrites direct participant/admin routes to the SPA entry point.
- Railway: FastAPI service and managed PostgreSQL database.
- Vercel and Railway terminate TLS; use the HTTPS frontend/API domains and WSS for WebSockets.
- Use a non-sleeping paid backend/database plan for event day. Capacity varies by plan; load-test before the event rather than assuming 100 concurrent teams are supported.

### Configure the frontend

Set these Vercel build environment variables, then deploy/rebuild:

```text
VITE_API_BASE_URL=https://<your-railway-api-domain>
VITE_WS_BASE_URL=wss://<your-railway-api-domain>
VITE_PUBLIC_APP_URL=https://<your-vercel-domain>
```

Production builds reject app/API URLs that do not use HTTPS or WebSocket URLs that do not use WSS. `VITE_PUBLIC_APP_URL` is public configuration, never a secret; it makes the organizer QR/join link use the canonical frontend domain. The backend's `PUBLIC_APP_URL` is also configured to the same canonical domain and is authoritative in API-generated responses.

### Configure the backend

Set the Railway service root directory to `backend`, install from `requirements.txt`, and use this start command:

```sh
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*
```

Configure these Railway variables:

```text
APP_ENV=production
DATABASE_URL=<Railway PostgreSQL connection URL>
ADMIN_PASSWORD=<a unique, strong organizer password>
ADMIN_SECRET=<at least 32 random characters, separate from ADMIN_PASSWORD>
FRONTEND_ORIGIN=https://<your-vercel-domain>
PUBLIC_APP_URL=https://<your-vercel-domain>
ALLOWED_HOSTS=<your-railway-api-domain>
```

Do not put backend secrets in Vite variables. `DATABASE_URL`, `ADMIN_PASSWORD`, and `ADMIN_SECRET` belong only in Railway's backend environment. The app accepts comma-separated frontend origins and host names. In production, only configured HTTPS origins pass CORS and HTTPS values are required for the public app and frontend origins. Host validation is enabled when `ALLOWED_HOSTS` is not `*`.

The backend accepts standard `postgres://` and `postgresql://` provider URLs and uses the Psycopg 3 driver. Startup creates/updates the question schema; it does not copy existing local quiz sessions or scores to PostgreSQL. If existing session history is needed, arrange and verify a separate data migration before the event.

### Deployment sequence

1. Create the managed PostgreSQL database and the backend service.
2. Set backend variables, including Railway's PostgreSQL URL, and deploy the API.
3. Confirm `https://<your-api-domain>/api/health` returns `{"ok":true}`.
4. Set the three Vercel variables to the real HTTPS/WSS hostnames and deploy the frontend.
5. Set `FRONTEND_ORIGIN` and `PUBLIC_APP_URL` to the exact deployed frontend origin, then redeploy the backend if changed.
6. Open `https://<your-frontend-domain>/admin/login`, create a test session, and confirm the QR points to `https://<your-frontend-domain>/join/<CODE>`.
7. Test with multiple real devices and run a load test before inviting all event teams.

## Quiz operations

Open `/admin/login`, create a session, share its QR/join link, and start the quiz once teams are ready. Organizer data is polled from the API; the WebSocket routes exist but the React app does not currently use them for dashboard updates.

Questions are in `backend/data/questions.json`. Do not remove or modify official questions/answer keys for the event.

## Deployment security and capacity notes

- Correct answers are excluded from participant question payloads and scoring is calculated on the backend.
- Admin API bearer tokens are signed with `ADMIN_SECRET`, expire after 12 hours, and can be verified across backend workers. The admin WebSocket requires the same signed token and an allowed origin.
- Team participant endpoints currently use the returned numeric team ID as their credential. This is acceptable for controlled MVP testing but is not strong authentication against deliberate ID guessing; before a public national event, replace it with a high-entropy participant capability/session token.
- The database engine supports PostgreSQL, but 100-team capacity depends on the selected database/service plan and should be measured with a realistic load test. SQLite remains for local development.
- Dashboard live updates currently use short polling, so WebSockets are not required for the current user interface. If switching the dashboard to WebSockets or deploying multiple workers with broadcast updates, add shared pub/sub (for example Redis) and load-test it.
