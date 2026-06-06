"""決算書の画像 → 主要財務項目の構造化JSON。

2つの抽出方式を持つ（EXTRACT_MODE で切替）:
  direct : VL に画像→スキーマ充填を一気にやらせる（単純な帳票向け・既定）
  2stage : VL=素のOCR → テキストモデル=項目抽出（複雑な実物の決算短信向け）
           VLは数字を読めるが表の項目対応が苦手、という実測に基づく分業。
"""
import json
import os

from tracing import op
from llm_client import vl_extract, jp_generate

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


# ---- 2段階方式（VL=OCR → テキストモデル=項目抽出）----------------------------
# Stage1: 素のOCR。スキーマ充填を求めず「見えるものをそのまま書き写す」だけ。
OCR_PROMPT = (
    "この決算書の画像の文字と数字を、表の行・列の構造を保ったまま全て正確に書き写してください（OCR）。"
    "金額の数字は省略せず、各項目名と同じ行に金額を書くこと。"
    "要約・解釈・推測はせず、画像に見えるものだけを出力してください。"
)

# Stage2: OCRテキスト → 8項目。テキストモデル（8081）の得意分野に寄せる。
PARSE_SYSTEM = (
    "あなたはOCRテキストから財務数値を抽出する専用エンジンです。"
    "与えられたOCRテキストのみに基づき指定項目を抽出し、JSONだけを出力します。"
    "前置き・説明・コードブロックは禁止。テキストから判断できない値は null。"
)
_PARSE_INSTR = (
    "以下は決算書をOCRしたテキストです（列ズレやノイズを含むことがあります）。\n"
    "各項目について『最新期（当期・当事業年度）』の金額を百万円の整数で抽出してください。\n"
    "増減率(%)・カッコ内の比率・1株当たり金額は『金額』ではないので採用しないこと。\n"
    "前期と当期が並ぶ場合は当期（通常は新しい年度）の値を採用すること。\n\n"
)
_PARSE_SCHEMA = ("【出力】次のスキーマのJSONのみ:\n"
                 + json.dumps(SCHEMA, ensure_ascii=False, indent=2))


def _parse_prompt(ocr_text: str, strict: bool = False) -> str:
    p = _PARSE_INSTR + "【OCRテキスト】\n" + ocr_text + "\n\n" + _PARSE_SCHEMA
    if strict:
        p += "\n必ず { から } までの有効なJSONのみを出力。説明禁止。"
    return p


def _parse_ocr_text(ocr_text: str, t_ocr: float):
    """OCRテキスト（VLでも専用OCRでも可）→ Liquid テキストモデルで8項目に構造化。"""
    parsed_json, t_parse = jp_generate(PARSE_SYSTEM, _parse_prompt(ocr_text))
    try:
        return parse_extraction(parsed_json), t_ocr + t_parse
    except (ValueError, json.JSONDecodeError):
        parsed2, t2 = jp_generate(PARSE_SYSTEM, _parse_prompt(ocr_text, strict=True))
        try:
            return parse_extraction(parsed2), t_ocr + t_parse + t2
        except (ValueError, json.JSONDecodeError):
            return normalize_schema({}), t_ocr + t_parse + t2


def ocr_engine_then_parse(image_bytes: bytes):
    """専用OCR(EasyOCR)で行構造テキスト → Liquid テキストモデルで項目抽出。
    VLが苦手な実物の密な決算短信向け。OCR=画素読み、Liquid=言語理解 の分業。"""
    from ocr_engine import ocr_rows
    ocr_text, t_ocr = ocr_rows(image_bytes)
    return _parse_ocr_text(ocr_text, t_ocr)


def ocr_then_parse(image_bytes: bytes):
    """VLで素のOCR → テキストモデルで項目抽出。実物の複雑な決算短信に強い。"""
    ocr_text, t_ocr = vl_extract(image_bytes, OCR_PROMPT)
    parsed_json, t_parse = jp_generate(PARSE_SYSTEM, _parse_prompt(ocr_text))
    try:
        return parse_extraction(parsed_json), t_ocr + t_parse
    except (ValueError, json.JSONDecodeError):
        # 抽出側がJSONを崩したら、もう一度だけJSON厳守で再依頼
        parsed2, t2 = jp_generate(PARSE_SYSTEM, _parse_prompt(ocr_text, strict=True))
        try:
            return parse_extraction(parsed2), t_ocr + t_parse + t2
        except (ValueError, json.JSONDecodeError):
            return normalize_schema({}), t_ocr + t_parse + t2


# Qwen-7B（ローカル・実物の密な表に強い）エンドポイント。オラクル兼「複雑文書」エンジン。
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8082/v1")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen2.5-vl")


def _direct_vl(image_bytes, base_url=None, model=None):
    """VLに直接スキーマ充填させる。崩れたら1回修復、それでも駄目なら全null（落とさない）。"""
    raw, latency = vl_extract(image_bytes, EXTRACT_PROMPT, base_url, model)
    try:
        return parse_extraction(raw), latency
    except (ValueError, json.JSONDecodeError):
        raw2, latency2 = vl_extract(image_bytes, REPAIR_PROMPT, base_url, model)
        try:
            return parse_extraction(raw2), latency + latency2
        except (ValueError, json.JSONDecodeError):
            return normalize_schema({}), latency + latency2


@op()
def extract_financials(image_bytes: bytes, engine: str = None):
    """決算書画像 → 構造化JSON。抽出エンジンを選べる:
      liquid_vl     : LFM2.5-VL に直接抽出（既定・高速・単純帳票向け）
      qwen_vl       : ローカルQwen-7B に直接抽出（実物の密な決算短信を読める）
      ocr           : 専用OCR(EasyOCR) → Liquid テキストモデルで項目抽出
      liquid_2stage : LFM-VLで素OCR → Liquid テキスト抽出
    どのエンジンでも後段（指標・格付け・所見）は Liquid が担う。"""
    engine = (engine or os.environ.get("EXTRACT_ENGINE", "liquid_vl")).lower()
    if engine == "ocr":
        return ocr_engine_then_parse(image_bytes)
    if engine == "qwen_vl":
        return _direct_vl(image_bytes, QWEN_BASE_URL, QWEN_MODEL)
    if engine == "liquid_2stage":
        return ocr_then_parse(image_bytes)
    return _direct_vl(image_bytes)  # liquid_vl（既定）
