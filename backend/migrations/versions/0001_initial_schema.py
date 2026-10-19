"""Create initial Cably tables."""
from alembic import op
from app.database import Base
from app import models  # noqa: F401

revision="0001_initial_schema"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    if bind.dialect.name=="postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    # Keep this revision frozen at the original schema. Later tables belong in
    # their own migrations so upgrades remain deterministic.
    Base.metadata.create_all(bind=bind, tables=[table for table in Base.metadata.sorted_tables if table.name != "ride_declines"])
    if bind.dialect.name=="postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS ix_drivers_location_gist ON drivers USING GIST ((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography))")

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
