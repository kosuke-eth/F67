"""抽出した財務数値 → 与信担当者向けのリスク所見。temperature=0 で決定性を担保。
財務指標は Python 側で決定的に算出し、モデルの計算ミスを土台から防ぐ。"""
import json

from tracing import op
from llm_client import jp_generate

SYSTEM = (
    "あなたは地方銀行の融資審査を補助するアシスタントです。"
    "提供された財務数値のみに基づき、事実に忠実に与信所見を作成します。"
    "数値にない事項は推測せず『情報不足』と明記します。断定的な融資可否は述べません。"
)

USER_TEMPLATE = (
    "以下の財務データから、融資稟議書の下書きとなる所見を作成してください。\n\n"
    "【財務データ】\n{data}\n\n"
    "【出力フォーマット】\n"
    "■ 概況（2〜3行）\n"
    "■ 主要な財務指標（提示された算出指標に言及）\n"
    "■ 注視すべきリスク（最大3点、根拠の数値とともに）\n"
    "■ 追加で確認すべき資料（情報不足の項目）\n"
)


def compute_ratios(data: dict) -> dict:
    """財務数値から基本指標を決定的に算出。"""
    out = {}

    def g(k):
        v = data.get(k)
        return v if isinstance(v, (int, float)) else None

    sales, op_p, na, ta, debt, cash = (
        g("売上高"), g("営業利益"), g("純資産"),
        g("総資産"), g("有利子負債"), g("現預金"))
    if na is not None and ta:
        out["自己資本比率(%)"] = round(100 * na / ta, 1)
    if op_p is not None and sales:
        out["営業利益率(%)"] = round(100 * op_p / sales, 1)
    if debt is not None and na:
        out["DEレシオ(倍)"] = round(debt / na, 2)
    if debt is not None and cash is not None:
        out["ネット有利子負債(百万円)"] = debt - cash
    return out


@op()
def risk_summary(data: dict):
    ratios = compute_ratios(data)
    payload = {"抽出値": data, "算出指標": ratios}
    user = USER_TEMPLATE.format(data=json.dumps(payload, ensure_ascii=False, indent=2))
    text, latency = jp_generate(SYSTEM, user)
    return text, latency, ratios
