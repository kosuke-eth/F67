"""NeoBank AI — オンプレ融資稟議アシスタント（Gradio デモUI）
決算書（画像 / PDF）を入れる → 端末内LFMで抽出 → 与信所見を生成。
すべてオンデバイス、外部ネットワーク通信なし。

起動: python app.py  →  http://localhost:7860
"""
import io
import json
import os

import gradio as gr
import pypdfium2 as pdfium
from PIL import Image

import tracing
from extract import extract_financials
from summarize import risk_summary
from llm_client import is_local_only
from make_sample import make_sample

tracing.init(os.environ.get("WEAVE_PROJECT", "neobank-ai"))


def _to_png_bytes(file_path: str) -> bytes:
    """画像 or PDF（1ページ目）を PNG バイト列に変換。"""
    if file_path.lower().endswith(".pdf"):
        pdf = pdfium.PdfDocument(file_path)
        pil = pdf[0].render(scale=2.0).to_pil()
    else:
        pil = Image.open(file_path).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def run(file_path):
    if not file_path:
        return "", "（決算書（画像/PDF）をアップロードしてください）", "", ""
    img_bytes = _to_png_bytes(file_path)

    data, t_extract = extract_financials(img_bytes)
    memo, t_summary, ratios, grade, warnings = risk_summary(data)

    extracted = json.dumps({"抽出値": data, "算出指標": ratios},
                           ensure_ascii=False, indent=2)

    # 暫定格付け＋整合性アラートのバッジ（決定的に算出＝監査可能）
    badge = f"暫定格付け: {grade.get('格付け')}（{grade.get('スコア')}）"
    if warnings:
        badge += "\n⚠️ 整合性アラート:\n" + "\n".join(f"・{w}" for w in warnings)
    else:
        badge += "\n✅ 整合性: 特記事項なし"

    net = "🔒 通信: ローカルのみ（外部送信なし）" if is_local_only() else "⚠️ 外部エンドポイント設定中"
    perf = (f"{net}\n抽出 {t_extract:.2f}s ／ 所見生成 {t_summary:.2f}s ／ "
            f"合計 {t_extract + t_summary:.2f}s")
    return extracted, memo, perf, badge


def load_sample():
    return make_sample()


with gr.Blocks(title="NeoBank AI — オンプレ融資稟議アシスタント") as demo:
    gr.Markdown(
        "# 🏦 NeoBank AI\n"
        "### オンプレ融資稟議アシスタント\n"
        "決算書を入れるだけで、**端末内**で財務数値を抽出し、与信稟議の下書きを生成します。"
        "顧客の財務データは一切外部に出ません。"
    )
    with gr.Row():
        with gr.Column():
            f = gr.File(label="決算書（画像 or PDF）",
                        file_types=[".png", ".jpg", ".jpeg", ".pdf"], type="filepath")
            with gr.Row():
                btn = gr.Button("稟議の下書きを作成", variant="primary")
                sample_btn = gr.Button("サンプルで試す")
            grade_out = gr.Textbox(label="暫定格付け / データ整合性（決定的算出）", lines=4)
            perf_out = gr.Textbox(label="オンデバイス性能 / 通信状況", lines=2)
        with gr.Column():
            memo_out = gr.Textbox(label="与信所見（下書き）", lines=16)
            json_out = gr.Code(label="抽出された財務データ", language="json")

    btn.click(run, inputs=f, outputs=[json_out, memo_out, perf_out, grade_out])
    sample_btn.click(load_sample, outputs=f)

if __name__ == "__main__":
    demo.launch()
