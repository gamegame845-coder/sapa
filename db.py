import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent   # backend 폴더
DB_PATH = BASE_DIR / "sapa.db"               # backend/sapa.db로 고정

DB_DIR = os.getenv("SAPA_DB_DIR", ".")
DB_PATH = Path(DB_DIR) / "app.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()