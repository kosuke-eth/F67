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
    "■ 暫定格付けの所見（提示された『暫定格付け』とその根拠に触れる）\n"
    "■ 注視すべきリスク（最大3点、根拠の数値とともに）\n"
    "■ データ整合性（『整合性アラート』があれば必ず明記。無ければ『特記事項なし』）\n"
    "■ 追加で確認すべき資料（情報不足の項目）\n"
)


def compute_ratios(data: dict) -> dict:
    """財務数値から基本指標を決定的に算出。"""
    out = {}

    def g(k):
        v = data.get(k)
        return v if isinstance(v, (int, float)) else None

    sales, op_p, ord_p, ni, na, ta, debt, cash = (
        g("売上高"), g("営業利益"), g("経常利益"), g("当期純利益"),
        g("純資産"), g("総資産"), g("有利子負債"), g("現預金"))
    if na is not None and ta:
        out["自己資本比率(%)"] = round(100 * na / ta, 1)
    if op_p is not None and sales:
        out["営業利益率(%)"] = round(100 * op_p / sales, 1)
    if ord_p is not None and sales:
        out["経常利益率(%)"] = round(100 * ord_p / sales, 1)
    if ni is not None and na:
        out["ROE(%)"] = round(100 * ni / na, 1)
    if ni is not None and ta:
        out["ROA(%)"] = round(100 * ni / ta, 1)
    if debt is not None and na:
        out["DEレシオ(倍)"] = round(debt / na, 2)
    if debt is not None and cash is not None:
        out["ネット有利子負債(百万円)"] = debt - cash

    # --- 成長性（前期比）---
    p_sales, p_op = g("前期売上高"), g("前期営業利益")
    if ni is not None and sales:
        out["当期純利益率(%)"] = round(100 * ni / sales, 1)
    if sales is not None and p_sales:
        out["売上高成長率(%)"] = round(100 * (sales - p_sales) / p_sales, 1)
    if op_p is not None and p_op:
        out["営業利益成長率(%)"] = round(100 * (op_p - p_op) / abs(p_op), 1)

    # --- キャッシュフロー & 返済能力（与信の核心）---
    ocf, icf = g("営業CF"), g("投資CF")
    if ocf is not None and sales:
        out["営業CFマージン(%)"] = round(100 * ocf / sales, 1)
    if ocf is not None and icf is not None:
        out["フリーCF(百万円)"] = ocf + icf          # 投資CFは通常マイナス
    if debt is not None and ocf and ocf > 0:
        out["債務償還年数(年)"] = round(debt / ocf, 1)  # 有利子負債 ÷ 営業CF
    # 利益の質: 当期純利益が営業CFで裏付けられているか（1.0以上が健全）
    if ocf is not None and ni and ni > 0:
        out["営業CF対純利益(倍)"] = round(ocf / ni, 2)
    # 借入余力の目安: 債務償還年数10年を上限としたときの追加借入可能額
    if ocf is not None and ocf > 0:
        out["借入余力目安(百万円)"] = int(round(ocf * 10 - (debt or 0)))
    return out


def validate_financials(data: dict) -> list:
    """会計の整合性チェック。実機VLの読み取りミスを土台で検知する
    （= 監査可能性の核。モデルが間違えても人が気づける）。
    返り値は警告メッセージのリスト（空ならクリーン）。"""
    warnings = []

    def g(k):
        v = data.get(k)
        return v if isinstance(v, (int, float)) else None

    ta, na, debt, cash = g("総資産"), g("純資産"), g("有利子負債"), g("現預金")
    if na is not None and ta is not None and na > ta:
        warnings.append(f"純資産({na}) が総資産({ta}) を上回っています。抽出ミスの疑い。")
    if cash is not None and ta is not None and cash > ta:
        warnings.append(f"現預金({cash}) が総資産({ta}) を上回っています。抽出ミスの疑い。")
    if debt is not None and ta is not None and debt > ta:
        warnings.append(f"有利子負債({debt}) が総資産({ta}) を上回っています。抽出ミスの疑い。")

    # 損益の整合性: 各利益は売上高を超えない（超えていれば行ズレ等の抽出ミス）。
    # 実機VLが「営業利益」に総資産の値を誤って割り当てる事故を確実に捕捉する。
    sales = g("売上高")
    for k in ("営業利益", "経常利益", "当期純利益"):
        p = g(k)
        if p is not None and sales is not None and p > sales:
            warnings.append(
                f"{k}({p}) が売上高({sales}) を上回っています。抽出ミスの疑い（行ズレ等）。")

    for k in ("総資産", "純資産", "売上高"):
        v = g(k)
        if v is not None and v < 0:
            warnings.append(f"{k} が負値({v})です。抽出ミスの疑い。")
    return warnings


# 与信格付け: 自己資本比率 / DEレシオ / 営業利益率 を決定的にスコア化（temperature非依存）
def risk_grade(ratios: dict):
    """3指標を 0-2 点で採点し合計 0-6 → A〜D の暫定格付け。
    根拠を併記して監査可能にする。指標が欠ければ採点対象外（点も満点も減る）。"""
    eq = ratios.get("自己資本比率(%)")
    de = ratios.get("DEレシオ(倍)")
    opm = ratios.get("営業利益率(%)")

    score, possible, reasons = 0, 0, []
    if eq is not None:
        possible += 2
        s = 2 if eq >= 40 else 1 if eq >= 20 else 0
        score += s
        reasons.append(f"自己資本比率 {eq}% → {s}/2")
    if de is not None:
        possible += 2
        s = 2 if de <= 1.0 else 1 if de <= 2.0 else 0
        score += s
        reasons.append(f"DEレシオ {de}倍 → {s}/2")
    if opm is not None:
        possible += 2
        s = 2 if opm >= 8 else 1 if opm >= 3 else 0
        score += s
        reasons.append(f"営業利益率 {opm}% → {s}/2")

    if possible == 0:
        return {"格付け": "判定不能", "スコア": None, "根拠": ["指標が算出できませんでした"]}
    pct = score / possible
    grade = "A" if pct >= 0.83 else "B" if pct >= 0.5 else "C" if pct >= 0.17 else "D"
    return {"格付け": grade, "スコア": f"{score}/{possible}", "根拠": reasons}


@op()
def risk_summary(data: dict):
    ratios = compute_ratios(data)
    warnings = validate_financials(data)
    grade = risk_grade(ratios)
    payload = {"抽出値": data, "算出指標": ratios,
               "暫定格付け": grade, "整合性アラート": warnings}
    user = USER_TEMPLATE.format(data=json.dumps(payload, ensure_ascii=False, indent=2))
    text, latency = jp_generate(SYSTEM, user)
    return text, latency, ratios, grade, warnings
