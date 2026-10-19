"""Persist driver ride declines."""
from alembic import op
import sqlalchemy as sa

revision = "0002_ride_declines"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    if "ride_declines" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "ride_declines",
            sa.Column("ride_id", sa.String(length=36), sa.ForeignKey("rides.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("driver_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    op.drop_table("ride_declines")
