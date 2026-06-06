"""開発用モックLFMサーバ（OpenAI互換）。
本物のLFMが無くても全パイプラインを動かせる。会場では起動せず、
.env を本物の llama.cpp エンドポイントに向ける。

起動:
    python mock_server.py            # VL を 8080
    python mock_server.py --port 8081  # JP を 8081
（VLとJPを別ポートで2つ起動する。中身は同じで内容で振り分ける）
"""
import argparse
import json

from flask import Flask, jsonify, request

from sample_data import SAMPLE_FINANCIALS

app = Flask(__name__)


def _has_image(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(p.get("type") == "image_url" for p in c):
            return True
    return False


def _text_of(messages, role):
    for m in messages:
        if m.get("role") == role:
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def _extract_payload(text):
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _make_memo(payload):
    data = payload.get("抽出値", {})
    r = payload.get("算出指標", {})
    grade = payload.get("暫定格付け", {})
    alerts = payload.get("整合性アラート", [])
    eq = r.get("自己資本比率(%)")
    opm = r.get("営業利益率(%)")
    de = r.get("DEレシオ(倍)")
    roe = r.get("ROE(%)")
    lines = [
        "■ 概況",
        f"{data.get('決算期', '当期')}は売上高{data.get('売上高')}百万円、"
        f"営業利益{data.get('営業利益')}百万円。黒字を確保しているが、"
        "利益率・財務レバレッジには留意が必要。",
        "",
        "■ 主要な財務指標",
        f"・自己資本比率: {eq}%" if eq is not None else "・自己資本比率: 情報不足",
        f"・営業利益率: {opm}%" if opm is not None else "・営業利益率: 情報不足",
        f"・ROE: {roe}%" if roe is not None else "・ROE: 情報不足",
        f"・DEレシオ: {de}倍" if de is not None else "・DEレシオ: 情報不足",
        "",
        "■ 暫定格付けの所見",
        (f"暫定格付けは {grade.get('格付け')}（スコア {grade.get('スコア')}）。"
         f"根拠: {' / '.join(grade.get('根拠', []))}。"
         "本格付けは決定的に算出され、同一書類なら常に同一結果（監査で再現可能）。"
         if grade.get("格付け") else "暫定格付け: 指標不足のため判定不能。"),
        "",
        "■ 注視すべきリスク",
        (f"1. 自己資本比率{eq}%とやや低位。下振れ耐性が限定的。" if eq is not None else "1. 自己資本比率を要確認。"),
        (f"2. DEレシオ{de}倍と有利子負債依存度が高い。金利上昇局面で負担増。" if de is not None else "2. 有利子負債水準を要確認。"),
        (f"3. 営業利益率{opm}%。同業比較での競争力を要検証。" if opm is not None else "3. 収益性を要確認。"),
        "",
        "■ データ整合性",
        ("特記事項なし（会計整合性チェックを通過）。" if not alerts
         else "次の不整合を検知。抽出値の再確認が必要:\n" + "\n".join(f"・{a}" for a in alerts)),
        "",
        "■ 追加で確認すべき資料",
        "・直近3期の推移、資金繰り表、主要取引先の与信状況、担保・保証の有無。",
        "",
        "※ 本所見はモックLFMによる開発用サンプル出力です。",
    ]
    return "\n".join(lines)


@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    messages = body.get("messages", [])

    if _has_image(messages):
        # 抽出タスク → サンプル財務JSONを返す
        content = json.dumps(SAMPLE_FINANCIALS, ensure_ascii=False)
    else:
        # 与信所見タスク → 渡された数値から所見を組み立てる
        payload = _extract_payload(_text_of(messages, "user"))
        content = _make_memo(payload)

    return jsonify({
        "id": "mock-cmpl",
        "object": "chat.completion",
        "model": body.get("model", "mock-lfm"),
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    app.run(host="127.0.0.1", port=args.port)
