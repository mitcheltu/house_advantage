"""
Database connection module — MySQL 8.0

Provides SQLAlchemy engine and session factory.
Reads credentials from .env file.
"""
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


def get_engine(database: str | None = None):
    """
    Create SQLAlchemy engine for MySQL 8.0.

    Args:
        database: Override database name (default: from MYSQL_DATABASE env var)
    """
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    db = database or os.getenv("MYSQL_DATABASE", "house_advantage")

    url = f"mysql+pymysql://{user}:{quote_plus(password)}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def get_session():
    """Create a new SQLAlchemy session."""
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def test_connection() -> bool:
    """Quick connectivity check."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"DB connection failed: {e}")
        return False
