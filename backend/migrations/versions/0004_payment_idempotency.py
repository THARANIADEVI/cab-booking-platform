"""Prevent duplicate successful charges for the same ride."""
from alembic import op
import sqlalchemy as sa

revision = "0004_payment_idempotency"
down_revision = "0003_ride_pickup_spatial_index"
branch_labels = None
depends_on = None


def upgrade():
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("payments")}
    if "uq_payments_successful_ride" not in indexes:
        op.create_index(
            "uq_payments_successful_ride",
            "payments",
            ["ride_id"],
            unique=True,
            sqlite_where=sa.text("ride_id IS NOT NULL AND status = 'succeeded' AND kind IN ('ride', 'wallet_ride')"),
            postgresql_where=sa.text("ride_id IS NOT NULL AND status = 'succeeded' AND kind IN ('ride', 'wallet_ride')"),
        )


def downgrade():
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("payments")}
    if "uq_payments_successful_ride" in indexes:
        op.drop_index("uq_payments_successful_ride", table_name="payments")
