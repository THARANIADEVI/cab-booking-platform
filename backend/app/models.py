from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    role: Mapped[str] = mapped_column(String(12), index=True)
    profile_pic: Mapped[str] = mapped_column(String(500), default="")
    rating_avg: Mapped[float] = mapped_column(Float, default=5.0)
    wallet_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Driver(Base):
    __tablename__ = "drivers"
    # PostgreSQL migrations derive a spatial POINT from these portable fields.
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    vehicle_info: Mapped[str] = mapped_column(String(180), default="Sedan · White")
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    latitude: Mapped[float] = mapped_column(Float, default=40.7128, index=True)
    longitude: Mapped[float] = mapped_column(Float, default=-74.0060, index=True)
    status: Mapped[str] = mapped_column(String(16), default="offline", index=True)

class Ride(Base):
    __tablename__ = "rides"
    # PostgreSQL migrations add generated pickup/drop POINT columns; SQLite keeps these coordinates.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rider_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    pickup: Mapped[str] = mapped_column(String(240))
    dropoff: Mapped[str] = mapped_column(String(240))
    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lng: Mapped[float] = mapped_column(Float)
    drop_lat: Mapped[float] = mapped_column(Float)
    drop_lng: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="requested", index=True)
    fare_estimate: Mapped[int] = mapped_column(Integer)
    fare_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_meters: Mapped[int] = mapped_column(Integer)
    duration_secs: Mapped[int] = mapped_column(Integer)
    promo_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class RideDecline(Base):
    __tablename__ = "ride_declines"
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id", ondelete="CASCADE"), primary_key=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index(
            "uq_payments_successful_ride",
            "ride_id",
            unique=True,
            sqlite_where=text("ride_id IS NOT NULL AND status = 'succeeded' AND kind IN ('ride', 'wallet_ride')"),
            postgresql_where=text("ride_id IS NOT NULL AND status = 'succeeded' AND kind IN ('ride', 'wallet_ride')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ride_id: Mapped[str | None] = mapped_column(ForeignKey("rides.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    kind: Mapped[str] = mapped_column(String(20), default="ride")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id"), index=True)
    rater_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    rated_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Promo(Base):
    __tablename__ = "promos"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    percent_off: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
