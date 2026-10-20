import os
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cably.db").strip()

# Render and other providers may supply the legacy ``postgres://`` scheme.
# SQLAlchemy 2 expects an explicit dialect, and this project installs psycopg v3.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

if urlsplit(DATABASE_URL).scheme in {"http", "https"}:
    raise ValueError(
        "DATABASE_URL must be a database connection string, not an HTTP(S) URL. "
        "Set it to your PostgreSQL connection string (for example, "
        "postgresql://user:password@host:5432/database)."
    )

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
