from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import re

import pandas as pd
import requests

try:
    import FinanceDataReader as fdr
except Exception:
    fdr = None


def _standardize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    입력 df가 어떤 형태든 아래 컬럼으로 표준화:
    date, open, high, low, close, volume
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    # index가 날짜인 경우 -> 컬럼으로
    if "date" not in [c.lower() for c in df.columns]:
        if isinstance(df.index, (pd.DatetimeIndex, pd.Index)):
            try:
                df = df.reset_index()
            except Exception:
                pass

    # 컬럼 소문자화
    df.columns = [str(c).strip().lower() for c in df.columns]

    # date 컬럼 이름이 다를 수 있어서 처리
    if "date" not in df.columns:
        # 흔한 케이스: index가 Date로 들어왔는데 reset_index 후 'index'로 잡히는 경우
        if "index" in df.columns:
            df = df.rename(columns={"index": "date"})
        elif "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})

    # finance-datareader는 보통 Open/High/... 형태
    rename_map = {}
    for k in ["open", "high", "low", "close", "volume"]:
        if k not in df.columns:
            # 혹시 대문자 섞여있던 경우 대비
            for cand in df.columns:
                if cand.lower() == k:
                    rename_map[cand] = k
    if rename_map:
        df = df.rename(columns=rename_map)

    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV 컬럼이 부족합니다: missing={missing}, columns={list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").copy()

    # 숫자형 변환
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["date", "close"]).copy()
    return df[required]


def _is_korea_ticker(ticker: str) -> bool:
    """
    MVP 기준:
    - 6자리 숫자면 한국(예: 005930)
    - 그 외는 미국(예: AAPL)
    """
    t = ticker.strip()
    return bool(re.fullmatch(r"\d{6}", t))


def fetch_us_from_stooq(ticker: str, years: int = 1) -> pd.DataFrame:
    """
    Stooq daily CSV: https://stooq.com/q/d/l/?s=aapl.us&i=d
    반환: 표준화된 OHLCV
    """
    t = ticker.strip().lower()

    # stooq 심볼 규칙: aapl.us
    # 이미 .us가 붙어있으면 그대로
    if not t.endswith(".us"):
        t = t + ".us"

    url = f"https://stooq.com/q/d/l/?s={t}&i=d"
    r = requests.get(url, timeout=20)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text))
    df = _standardize_ohlcv(df)

    # 기간 필터
    end = datetime.now()
    start = end - timedelta(days=365 * int(years))
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))].copy()

    return df


def fetch_kr_from_fdr(ticker: str, years: int = 1) -> pd.DataFrame:
    """
    FinanceDataReader: fdr.DataReader('005930', start, end)
    반환: 표준화된 OHLCV
    """
    if fdr is None:
        raise ValueError("FinanceDataReader가 설치되지 않았습니다. pip install finance-datareader")

    end = datetime.now().date()
    start = (datetime.now() - timedelta(days=365 * int(years))).date()

    df = fdr.DataReader(ticker.strip(), str(start), str(end))
    df = _standardize_ohlcv(df)
    return df


def fetch_ohlcv(ticker: str, years: int = 1) -> pd.DataFrame:
    """
    공통 진입점:
    - 한국(6자리 숫자): FinanceDataReader
    - 미국(그 외): Stooq
    """
    t = ticker.strip()
    if not t:
        raise ValueError("ticker is empty")

    if _is_korea_ticker(t):
        df = fetch_kr_from_fdr(t, years=years)
        if df is None or df.empty:
            raise ValueError(f"KR 데이터를 가져오지 못했습니다: {t}")
        return df

    # US
    df = fetch_us_from_stooq(t, years=years)
    if df is None or df.empty:
        raise ValueError(f"US 데이터를 가져오지 못했습니다: {t}")
    return df
