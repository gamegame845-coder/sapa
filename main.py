import os
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from ai_comment import make_ai_comment_korean
from analysis_engine import compute_indicators, rule_result_from_df
from backtest_engine import backtest_score_bins
from data_provider import fetch_ohlcv
from db import Base, SessionLocal, engine
from models import Watchlist

# ✅ boards router
from boards import init_db as boards_init_db
from boards import router as boards_router

print("RUNNING main.py =>", os.path.abspath(__file__))

app = FastAPI()

origins = os.getenv(
    "SAPA_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ boards DB init + router mount (중복 라우트 방지: main.py에는 게시판 API를 절대 만들지 않음)
boards_init_db()
app.include_router(boards_router)

# ✅ SQLAlchemy tables
Base.metadata.create_all(bind=engine)


# ---------- DB Session Dependency ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- health ----------
@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat()}


# ---------- analysis ----------
@app.get("/analysis/{ticker}")
def analysis(ticker: str, ai: int = Query(0)):
    try:
        df = fetch_ohlcv(ticker, years=1)
        if df is None or len(df) < 60:
            raise ValueError("가격 데이터가 비어있거나 너무 적습니다.")

        df = compute_indicators(df)
        rr = rule_result_from_df(df)

        comment = rr["comment_rule"]
        if ai == 1:
            try:
                comment = make_ai_comment_korean(
                    ticker, rr["rating"], rr["score"], rr["features"], rr["reasons"]
                )
            except Exception:
                comment = rr["comment_rule"]

        return {
            "ticker": ticker,
            "rating": rr["rating"],
            "score": rr["score"],
            "comment": comment,
            "features": rr["features"],
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {str(e)}")


# ---------- watchlist ----------
@app.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()
    return [
        {
            "ticker": w.ticker,
            "market": w.market,
            "created_at": w.created_at.isoformat(),
        }
        for w in items
    ]


@app.post("/watchlist/{ticker}")
def add_watchlist(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.strip()
    if not ticker:
        return {"ok": False, "message": "ticker is empty"}

    exists = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
    if exists:
        return {"ok": True, "message": "already exists", "ticker": ticker}

    w = Watchlist(ticker=ticker)
    db.add(w)
    db.commit()
    return {"ok": True, "ticker": ticker}


@app.delete("/watchlist/{ticker}")
def delete_watchlist(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.strip()
    w = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
    if not w:
        return {"ok": True, "message": "not found", "ticker": ticker}

    db.delete(w)
    db.commit()
    return {"ok": True, "ticker": ticker}


# ---------- dashboard ----------
@app.get("/dashboard")
def dashboard(ai: int = 0, db: Session = Depends(get_db)):
    items = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()

    out = []
    for w in items:
        ticker = w.ticker
        try:
            df = fetch_ohlcv(ticker, years=1)
            df = compute_indicators(df)
            rr = rule_result_from_df(df)

            comment = rr["comment_rule"]
            if ai == 1:
                try:
                    comment = make_ai_comment_korean(
                        ticker, rr["rating"], rr["score"], rr["features"], rr["reasons"]
                    )
                except Exception:
                    comment = rr["comment_rule"]

            out.append(
                {
                    "ticker": ticker,
                    "market": w.market,
                    "rating": rr["rating"],
                    "score": rr["score"],
                    "comment": comment,
                    "features": rr["features"],
                    "updated_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            out.append(
                {
                    "ticker": ticker,
                    "market": w.market,
                    "error": f"{type(e).__name__}: {str(e)}",
                    "updated_at": datetime.now().isoformat(),
                }
            )

    return {"items": out}


# ---------- ohlcv ----------
@app.get("/ohlcv/{ticker}")
def ohlcv(ticker: str, years: int = 1):
    try:
        df = fetch_ohlcv(ticker, years=years)
        if df is None or df.empty:
            raise ValueError("empty ohlcv")

        data = [
            {
                "date": row["date"].date().isoformat(),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if row["volume"] is not None else 0.0,
            }
            for _, row in df.iterrows()
        ]
        return {"ticker": ticker, "years": years, "items": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {str(e)}")


# ---------- forecast ----------
@app.get("/forecast/{ticker}")
def forecast(ticker: str, days: int = 30, years: int = 1):
    try:
        df = fetch_ohlcv(ticker, years=years)
        if df is None or df.empty or len(df) < 60:
            raise ValueError("not enough data")

        df = df.copy()
        df["close"] = df["close"].astype(float)
        last_date = pd.to_datetime(df["date"].iloc[-1])
        close = df["close"].values

        rets = np.diff(close) / close[:-1]
        mu = float(np.mean(rets))
        sigma = float(np.std(rets))
        last = float(close[-1])

        future_dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=days, freq="B")

        path = []
        for i, d in enumerate(future_dates, start=1):
            exp = last * ((1 + mu) ** i)
            band = last * (sigma * (i ** 0.5))
            path.append(
                {
                    "date": d.date().isoformat(),
                    "expected": float(exp),
                    "upper": float(exp + band),
                    "lower": float(max(0.0, exp - band)),
                }
            )

        return {
            "ticker": ticker,
            "days": days,
            "years": years,
            "last": last,
            "mu": mu,
            "sigma": sigma,
            "items": path,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {str(e)}")


# ---------- backtest ----------
@app.get("/backtest/{ticker}")
def backtest(ticker: str, horizon: int = 20, years: int = 3):
    df = fetch_ohlcv(ticker, years=years)
    result = backtest_score_bins(df, horizon=horizon)
    return {"ticker": ticker, "years": years, **result}
