# Cably cab booking platform

Cably is a full-stack ride booking MVP built from `_Python - Cab Booking Platform.pdf`.

## Features

- Rider and driver accounts with role-based access; Clerk JWT verification when configured and local demo accounts otherwise.
- Ride fare estimates, promo codes, booking, nearest-driver dispatch, driver accept/decline, and trip status updates.
- Driver availability and live GPS updates over FastAPI WebSockets, with optional Redis pub/sub for multiple API workers.
- Suggested pickup/drop-off locations plus Google geocoding for custom addresses; Google Maps distance and duration estimates when configured, with a Haversine fallback and an OpenStreetMap map when no browser key is set.
- Stripe PaymentIntents and signed webhook handling, wallet ride payments, and a local demo payment flow.
- Ride history, PDF receipts, optional Celery receipt emails, ratings/reviews, and wallet top-ups with a transaction ledger.
- PostgreSQL/PostGIS support with generated `POINT` columns and spatial indexes, SQLite local development with Haversine matching, Alembic migrations, CORS configuration, and rate limiting.

## Run locally on Windows (without Docker)

Use three PowerShell windows from this project folder.

### 1. Configure the backend

```powershell
Copy-Item .env.example .env
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
```

The default database is a local SQLite file. External services are optional for development.

### 2. Start the API

In the first PowerShell window, from `backend`:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`.

### 3. Configure and start the web app

In a second PowerShell window:

```powershell
cd frontend
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Start with the local demo accounts and use the profile switcher at the bottom of the sidebar to change between rider and driver:

- Rider: `Bearer dev-rider`
- Driver: `Bearer dev-driver`

The driver demo starts online. To test a complete ride, open the web app in two browser windows (one rider, one driver), request a ride, accept it as the driver, and advance it through the trip buttons.

## Optional integrations

Set keys in the root `.env` and/or `frontend/.env.local` as appropriate:

- **Clerk:** set `CLERK_JWKS_URL`, `CLERK_ISSUER`, and `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`. Add the `role` (`rider` or `driver`) to the Clerk public metadata and expose public metadata in the session token claims.
- **Google Maps:** set backend `GOOGLE_MAPS_API_KEY`; set frontend `NEXT_PUBLIC_GOOGLE_MAPS_KEY` and optionally `NEXT_PUBLIC_GOOGLE_MAP_ID`.
- **Stripe:** set backend `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`; set frontend `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.
- **Redis and Celery:** set `REDIS_URL` for shared rate limits and real-time pub/sub. Set `CELERY_BROKER_URL` to enable background receipt email jobs, and configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` for email delivery. Run a Celery worker separately when using background email jobs.
- **PostgreSQL/PostGIS:** set `DATABASE_URL` to a PostGIS-enabled PostgreSQL database before running `alembic upgrade head`.

Do not use the development bearer tokens in production. Keep secret keys in the backend environment only.

To run the optional receipt worker on Windows, open another PowerShell window, activate `backend\.venv`, change to `backend`, then run:

```powershell
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```
