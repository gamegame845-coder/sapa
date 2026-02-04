from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from db import Base

class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True, nullable=False)
    market = Column(String, default="KR", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
