"""決算書の画像 → 主要財務項目の構造化JSON。LFM2.5-VL-1.6B を抽出専用プロンプトで拘束して使う。"""
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
    "金額は百万円単位の整数（カンマ・単位記号なし）。\n"
    "【重要】各項目は、その項目名と同じ行に書かれた数値だけを読むこと。\n"
    "【重要】前期と当期（または複数期）が併記されている場合は、必ず最新期"
    "（当期・当事業年度＝通常は右側の列）の数値を採用すること。前期の値は使わない。\n\n"
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
    return normalize_schema(data)


def normalize_schema(data: dict) -> dict:
    """スキーマ通りの形に整える。欠損キーは null 補完、数値は整数化、
    余計なキーは捨てる。実モデルの揺れ（余分なキー・欠損）を吸収する。"""
    out = {}
    for k in SCHEMA:
        v = data.get(k)
        out[k] = _coerce_int(v) if k in _NUMERIC_KEYS else v
    return out


# 解析に失敗したときの自己修復用プロンプト（JSONのみを再要求）
REPAIR_PROMPT = (
    EXTRACT_PROMPT
    + "\n\n【重要】前回の出力はJSONとして解析できませんでした。"
    "必ず { から } までの有効なJSONのみを出力してください。説明・コードブロックは禁止。"
)


@op()
def extract_financials(image_bytes: bytes):
    """決算書画像 → 構造化JSON。1度パースに失敗したら修復プロンプトで再試行する
    （実機のVLは出力が揺れるため、1回のリトライで成功率を大きく上げる）。"""
    raw, latency = vl_extract(image_bytes, EXTRACT_PROMPT)
    try:
        return parse_extraction(raw), latency
    except (ValueError, json.JSONDecodeError):
        raw2, latency2 = vl_extract(image_bytes, REPAIR_PROMPT)
        # 再試行も失敗すれば元の例外を伝播させる（呼び出し側で扱う）
        return parse_extraction(raw2), latency + latency2
