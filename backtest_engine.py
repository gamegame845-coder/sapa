import numpy as np
import pandas as pd
from analysis_engine import compute_indicators, _score_from_row

def backtest_score_bins(df_raw: pd.DataFrame, horizon: int = 20) -> dict:
    """
    df_raw: date, open, high, low, close, volume
    horizon: 이후 n거래일 수익률
    """
    df = compute_indicators(df_raw)
    df = df.reset_index(drop=True)

    # 미래 수익률(lookahead)
    df["fwd_ret"] = df["close"].shift(-horizon) / df["close"] - 1.0

    rows = []
    # 지표 안정적으로 나오는 구간부터(대략 252일 이상 권장)
    start_i = 260
    end_i = len(df) - horizon - 1

    if end_i <= start_i:
        return {"ok": False, "message": "백테스트에 필요한 데이터가 부족합니다."}

    for i in range(start_i, end_i):
        score, _, _ = _score_from_row(df.iloc[i])
        fwd = df.loc[i, "fwd_ret"]
        if pd.isna(fwd):
            continue
        rows.append((score, float(fwd)))

    if not rows:
        return {"ok": False, "message": "백테스트 표본이 생성되지 않았습니다."}

    arr = np.array(rows)
    scores = arr[:, 0]
    rets = arr[:, 1]

    # 구간 정의
    bins = [
        (80, 100, "적극매수권(80-100)"),
        (60, 79,  "매수권(60-79)"),
        (40, 59,  "중립권(40-59)"),
        (20, 39,  "매도권(20-39)"),
        (0,  19,  "적극매도권(0-19)"),
    ]

    out = []
    for lo, hi, name in bins:
        mask = (scores >= lo) & (scores <= hi)
        n = int(mask.sum())
        if n == 0:
            out.append({"bin": name, "n": 0, "win_rate": None, "avg_return": None})
            continue
        rr = rets[mask]
        win_rate = float((rr > 0).mean())
        avg_return = float(rr.mean())
        out.append({"bin": name, "n": n, "win_rate": win_rate, "avg_return": avg_return})

    # 전체 통계
    overall = {
        "n": int(len(rets)),
        "win_rate": float((rets > 0).mean()),
        "avg_return": float(rets.mean()),
    }

    return {"ok": True, "overall": overall, "bins": out, "horizon": horizon}
