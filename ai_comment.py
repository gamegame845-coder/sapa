import os
import json

def make_ai_comment_korean(ticker: str, rating: str, score: int, features: dict, reasons: list[str]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")

    # 키가 있을 때만 import + client 생성
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    system_ko = """너는 주식 분석 코멘트 작성 보조자다.
규칙 엔진이 계산한 값(features/reasons/score/rating)만 사용해 한국어로 코멘트를 작성한다.
새로운 숫자/사실/뉴스를 만들지 말고, 입력에 없는 내용은 추측하지 마라.
출력은 3~5문장으로 간결하게. 마지막 문장에 '주의: 투자 판단은 본인 책임'을 포함해라.
"""

    payload = {
        "ticker": ticker,
        "rating": rating,
        "score": score,
        "features": features,
        "reasons": reasons[:8],
    }

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_ko},
            {"role": "user", "content": "다음 JSON을 근거로 코멘트를 작성해줘:\n" + json.dumps(payload, ensure_ascii=False)}
        ],
    )
    return resp.output_text.strip()
