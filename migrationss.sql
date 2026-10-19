-- Cably cab booking platform: PostgreSQL/Supabase schema
-- Apply once in Supabase Dashboard -> SQL Editor.
-- This is the equivalent of Alembic revisions 0001 through 0004 plus the
-- PostGIS columns and indexes added by backend/app/main.py.
--
-- PostGIS should live in Supabase's `extensions` schema. This app connects
-- through its FastAPI backend using DATABASE_URL; do not expose these tables
-- directly to anon/authenticated clients unless you add reviewed RLS policies.

BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS public.users (
    id varchar(36) PRIMARY KEY,
    name varchar(120) NOT NULL,
    email varchar(254) NOT NULL,
    phone varchar(30) NOT NULL,
    role varchar(12) NOT NULL,
    profile_pic varchar(500) NOT NULL,
    rating_avg double precision NOT NULL,
    wallet_cents integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS public.drivers (
    user_id varchar(36) PRIMARY KEY REFERENCES public.users(id),
    vehicle_info varchar(180) NOT NULL,
    verified boolean NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    status varchar(16) NOT NULL,
    current_location extensions.geometry(Point,4326)
        GENERATED ALWAYS AS (extensions.ST_SetSRID(extensions.ST_MakePoint(longitude, latitude), 4326)) STORED
);

CREATE TABLE IF NOT EXISTS public.rides (
    id varchar(36) PRIMARY KEY,
    rider_id varchar(36) NOT NULL REFERENCES public.users(id),
    driver_id varchar(36) REFERENCES public.users(id),
    pickup varchar(240) NOT NULL,
    dropoff varchar(240) NOT NULL,
    pickup_lat double precision NOT NULL,
    pickup_lng double precision NOT NULL,
    drop_lat double precision NOT NULL,
    drop_lng double precision NOT NULL,
    status varchar(24) NOT NULL,
    fare_estimate integer NOT NULL,
    fare_actual integer,
    distance_meters integer NOT NULL,
    duration_secs integer NOT NULL,
    promo_code varchar(32),
    created_at timestamp with time zone NOT NULL,
    pickup_point extensions.geometry(Point,4326)
        GENERATED ALWAYS AS (extensions.ST_SetSRID(extensions.ST_MakePoint(pickup_lng, pickup_lat), 4326)) STORED,
    drop_point extensions.geometry(Point,4326)
        GENERATED ALWAYS AS (extensions.ST_SetSRID(extensions.ST_MakePoint(drop_lng, drop_lat), 4326)) STORED
);

CREATE TABLE IF NOT EXISTS public.ride_declines (
    ride_id varchar(36) NOT NULL REFERENCES public.rides(id) ON DELETE CASCADE,
    driver_id varchar(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    created_at timestamp with time zone,
    PRIMARY KEY (ride_id, driver_id)
);

CREATE TABLE IF NOT EXISTS public.payments (
    id varchar(36) PRIMARY KEY,
    ride_id varchar(36) REFERENCES public.rides(id),
    user_id varchar(36) NOT NULL REFERENCES public.users(id),
    stripe_payment_intent_id varchar(160) UNIQUE,
    amount integer NOT NULL,
    status varchar(24) NOT NULL,
    kind varchar(20) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS public.reviews (
    id varchar(36) PRIMARY KEY,
    ride_id varchar(36) NOT NULL REFERENCES public.rides(id),
    rater_id varchar(36) NOT NULL REFERENCES public.users(id),
    rated_id varchar(36) NOT NULL REFERENCES public.users(id),
    rating integer NOT NULL,
    comment text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS public.promos (
    code varchar(32) PRIMARY KEY,
    percent_off integer NOT NULL,
    active boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS public.wallet_transactions (
    id varchar(36) PRIMARY KEY,
    user_id varchar(36) NOT NULL REFERENCES public.users(id),
    amount integer NOT NULL,
    description varchar(180) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- Indexes from SQLAlchemy model metadata and Alembic migrations.
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON public.users (email);
CREATE INDEX IF NOT EXISTS ix_users_role ON public.users (role);
CREATE INDEX IF NOT EXISTS ix_drivers_latitude ON public.drivers (latitude);
CREATE INDEX IF NOT EXISTS ix_drivers_longitude ON public.drivers (longitude);
CREATE INDEX IF NOT EXISTS ix_drivers_status ON public.drivers (status);
CREATE INDEX IF NOT EXISTS ix_drivers_current_location_gist
    ON public.drivers USING GIST ((current_location::extensions.geography));
CREATE INDEX IF NOT EXISTS ix_rides_rider_id ON public.rides (rider_id);
CREATE INDEX IF NOT EXISTS ix_rides_driver_id ON public.rides (driver_id);
CREATE INDEX IF NOT EXISTS ix_rides_status ON public.rides (status);
CREATE INDEX IF NOT EXISTS ix_rides_created_at ON public.rides (created_at);
CREATE INDEX IF NOT EXISTS ix_rides_pickup_gist
    ON public.rides USING GIST ((pickup_point::extensions.geography));
CREATE INDEX IF NOT EXISTS ix_payments_ride_id ON public.payments (ride_id);
CREATE INDEX IF NOT EXISTS ix_payments_user_id ON public.payments (user_id);
CREATE INDEX IF NOT EXISTS ix_reviews_ride_id ON public.reviews (ride_id);
CREATE INDEX IF NOT EXISTS ix_reviews_rater_id ON public.reviews (rater_id);
CREATE INDEX IF NOT EXISTS ix_reviews_rated_id ON public.reviews (rated_id);
CREATE INDEX IF NOT EXISTS ix_wallet_transactions_user_id ON public.wallet_transactions (user_id);

-- Migration 0004: one successful ride/wallet_ride payment per ride.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_successful_ride
    ON public.payments (ride_id)
    WHERE ride_id IS NOT NULL
      AND status = 'succeeded'
      AND kind IN ('ride', 'wallet_ride');

-- Seed the promo codes created by the app on first startup.
INSERT INTO public.promos (code, percent_off, active)
VALUES ('WELCOME20', 20, true), ('CITY10', 10, true)
ON CONFLICT (code) DO NOTHING;

-- The application uses FastAPI + DATABASE_URL rather than Supabase client-side
-- access. Enable RLS so the Supabase Data API cannot read/write app tables by
-- default. The backend's direct database role must have the required access.
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ride_declines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.promos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wallet_transactions ENABLE ROW LEVEL SECURITY;

COMMIT;
