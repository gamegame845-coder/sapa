import pandas as pd
import numpy as np
import pandas_ta as ta

def score_to_rating(score: int) -> str:
    if score >= 80: return "적극매수"
    if score >= 60: return "매수"
    if score >= 40: return "중립"
    if score >= 20: return "매도"
    return "적극매도"

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["ret"] = df["close"].pct_change()

    df["rsi14"] = ta.rsi(df["close"], length=14)

    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma120"] = df["close"].rolling(120).mean()

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]

    df["vol20_pct"] = df["ret"].rolling(20).std() * np.sqrt(20) * 100.0

    df["mom20"] = df["close"] / df["close"].shift(20) - 1.0
    df["mom60"] = df["close"] / df["close"].shift(60) - 1.0

    df["high252"] = df["close"].rolling(252).max()
    df["dd252"] = df["close"] / df["high252"] - 1.0

    df["low20"] = df["close"].rolling(20).min()
    df["high20"] = df["close"].rolling(20).max()
    df["pos20"] = (df["close"] - df["low20"]) / (df["high20"] - df["low20"] + 1e-9)

    return df

def _score_from_row(row: pd.Series) -> tuple[int, list[str], dict]:
    close = float(row["close"])
    rsi = row.get("rsi14", np.nan)
    ma20 = row.get("ma20", np.nan)
    ma60 = row.get("ma60", np.nan)
    ma120 = row.get("ma120", np.nan)
    vol_ratio = row.get("vol_ratio", np.nan)
    vol20 = row.get("vol20_pct", np.nan)
    mom20 = row.get("mom20", np.nan)
    mom60 = row.get("mom60", np.nan)
    dd252 = row.get("dd252", np.nan)
    pos20 = row.get("pos20", np.nan)

    s = 50
    reasons: list[str] = []

    def above(x): return pd.notna(x) and close > float(x)

    if pd.notna(ma20):
        s += 8 if above(ma20) else -8
        reasons.append("20일선 위" if above(ma20) else "20일선 아래")
    if pd.notna(ma60):
        s += 10 if above(ma60) else -10
        reasons.append("60일선 위" if above(ma60) else "60일선 아래")
    if pd.notna(ma120):
        s += 6 if above(ma120) else -6
        reasons.append("120일선 위" if above(ma120) else "120일선 아래")

    if pd.notna(ma20) and pd.notna(ma60) and pd.notna(ma120):
        if float(ma20) > float(ma60) > float(ma120):
            s += 8; reasons.append("이평 정배열(상승 추세 정렬)")
        elif float(ma20) < float(ma60) < float(ma120):
            s -= 8; reasons.append("이평 역배열(하락 추세 정렬)")

    if pd.notna(rsi):
        r = float(rsi)
        if r < 30:
            s += 10; reasons.append(f"RSI {r:.1f}(과매도)")
        elif r > 70:
            s -= 10; reasons.append(f"RSI {r:.1f}(과매수)")
        else:
            reasons.append(f"RSI {r:.1f}(중립)")

    if pd.notna(mom20):
        m = float(mom20)
        if m > 0.08:
            s += 6; reasons.append(f"1개월 모멘텀 +{m*100:.1f}%")
        elif m < -0.08:
            s -= 6; reasons.append(f"1개월 모멘텀 {m*100:.1f}%")

    if pd.notna(mom60):
        m = float(mom60)
        if m > 0.15:
            s += 6; reasons.append(f"3개월 모멘텀 +{m*100:.1f}%")
        elif m < -0.15:
            s -= 6; reasons.append(f"3개월 모멘텀 {m*100:.1f}%")

    if pd.notna(vol_ratio):
        vr = float(vol_ratio)
        if vr >= 1.8:
            s += 8; reasons.append(f"거래량 급증({vr:.2f}배)")
        elif vr <= 0.6:
            s -= 3; reasons.append(f"거래량 위축({vr:.2f}배)")

    if pd.notna(vol20):
        v = float(vol20)
        if v >= 35:
            s -= 5; reasons.append(f"변동성 높음({v:.1f}%)")
        elif v <= 15:
            s += 2; reasons.append(f"변동성 낮음({v:.1f}%)")

    if pd.notna(dd252):
        dd = float(dd252)
        if dd <= -0.30:
            s += 5; reasons.append(f"52주 고점 대비 {dd*100:.0f}% (낙폭)")
        elif dd >= -0.05:
            s -= 3; reasons.append("52주 고점 근처(추격 부담)")

    if pd.notna(pos20):
        p = float(pos20)
        if p <= 0.15:
            s += 3; reasons.append("최근 20일 저점권(지지 테스트)")
        elif p >= 0.85:
            s -= 2; reasons.append("최근 20일 고점권(저항/과열)")

    s = int(max(0, min(100, s)))

    features = {
        "close": close,
        "rsi14": float(rsi) if pd.notna(rsi) else None,
        "ma20": float(ma20) if pd.notna(ma20) else None,
        "ma60": float(ma60) if pd.notna(ma60) else None,
        "ma120": float(ma120) if pd.notna(ma120) else None,
        "vol_ratio": float(vol_ratio) if pd.notna(vol_ratio) else None,
        "vol20_pct": float(vol20) if pd.notna(vol20) else None,
        "mom20": float(mom20) if pd.notna(mom20) else None,
        "mom60": float(mom60) if pd.notna(mom60) else None,
        "dd252": float(dd252) if pd.notna(dd252) else None,
        "pos20": float(pos20) if pd.notna(pos20) else None,
    }
    return s, reasons, features

def rule_result_from_df(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    score, reasons, features = _score_from_row(last)
    rating = score_to_rating(score)
    comment_rule = f"{rating} (점수 {score}). " + " / ".join(reasons[:5])
    return {
        "score": score,
        "rating": rating,
        "comment_rule": comment_rule,
        "features": features,
        "reasons": reasons,
    }
