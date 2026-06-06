"""決算書の画像 → 主要財務項目の構造化JSON。抽出専用 LFM2.5-VL-Extract を使う。"""
import json

from tracing import op
from llm_client import vl_extract

SCHEMA = {
    "決算期": "例: 2025年3月期",
    "売上高": "百万円。整数。カンマ・単位なし",
    "営業利益": "百万円。整数",
    "経常利益": "百万円。整数",
    "当期純利益": "百万円。整数",
    "総資産": "百万円。整数",
    "純資産": "百万円。整数",
    "有利子負債": "百万円。整数",
    "現預金": "百万円。整数",
}

EXTRACT_PROMPT = (
    "あなたは財務書類の読み取り専用エンジンです。"
    "添付の決算書画像から以下の項目を読み取り、JSONのみを出力。"
    "前置き・説明・コードブロック禁止。読み取れない項目は null。\n"
    "金額は百万円単位の整数（カンマ・単位記号なし）。\n\n"
    "スキーマ:\n" + json.dumps(SCHEMA, ensure_ascii=False, indent=2)
)

# 数値化したいキー（"1,234" や "1234百万円" を整数に正規化）
_NUMERIC_KEYS = [k for k in SCHEMA if k != "決算期"]


def _coerce_int(v):
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").replace("百万円", "").replace("円", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_extraction(text: str) -> dict:
    """モデル出力からJSONを頑健に取り出し、数値を正規化する。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSONが見つかりません: {text[:200]}")
    data = json.loads(text[start:end + 1])
    for k in _NUMERIC_KEYS:
        if k in data:
            data[k] = _coerce_int(data[k])
    return data


@op()
def extract_financials(image_bytes: bytes):
    raw, latency = vl_extract(image_bytes, EXTRACT_PROMPT)
    return parse_extraction(raw), latency
