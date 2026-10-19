"""Index ride pickup points for PostGIS dispatch."""
from alembic import op

revision = "0003_ride_pickup_spatial_index"
down_revision = "0002_ride_declines"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        op.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS current_location geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude,latitude),4326)) STORED")
        op.execute("ALTER TABLE rides ADD COLUMN IF NOT EXISTS pickup_point geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(pickup_lng,pickup_lat),4326)) STORED")
        op.execute("ALTER TABLE rides ADD COLUMN IF NOT EXISTS drop_point geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(drop_lng,drop_lat),4326)) STORED")
        op.execute("DROP INDEX IF EXISTS ix_drivers_location_gist")
        op.execute("CREATE INDEX IF NOT EXISTS ix_drivers_current_location_gist ON drivers USING GIST ((current_location::geography))")
        op.execute("CREATE INDEX IF NOT EXISTS ix_rides_pickup_gist ON rides USING GIST ((pickup_point::geography))")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_rides_pickup_gist")
        op.execute("DROP INDEX IF EXISTS ix_drivers_current_location_gist")
        op.execute("ALTER TABLE rides DROP COLUMN IF EXISTS pickup_point")
        op.execute("ALTER TABLE rides DROP COLUMN IF EXISTS drop_point")
        op.execute("ALTER TABLE drivers DROP COLUMN IF EXISTS current_location")
        op.execute("CREATE INDEX IF NOT EXISTS ix_drivers_location_gist ON drivers USING GIST ((ST_SetSRID(ST_MakePoint(longitude,latitude),4326)::geography))")
