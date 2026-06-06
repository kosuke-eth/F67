"""NeoBank AI — On-Premise Credit Underwriting Assistant (Gradio UI).

Drop in a financial statement (image / PDF) → on-device LFM extracts the figures →
deterministic engine computes ratios, a provisional rating, and audit checks →
on-device JP model drafts the credit opinion. Nothing leaves the machine.

Run:  python app.py  →  http://localhost:7860
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

# --- English labels alongside the Japanese source fields (content stays JP) ---
FIELD_EN = {
    "売上高": "Net Sales", "営業利益": "Operating Income", "経常利益": "Ordinary Income",
    "当期純利益": "Net Income", "総資産": "Total Assets", "純資産": "Net Assets",
    "有利子負債": "Interest-bearing Debt", "現預金": "Cash & Deposits",
}
PL_KEYS = ["売上高", "営業利益", "経常利益", "当期純利益"]
BS_KEYS = ["総資産", "純資産", "有利子負債", "現預金"]
RATIO_EN = {
    "自己資本比率(%)": ("Equity Ratio", "%"), "営業利益率(%)": ("Operating Margin", "%"),
    "経常利益率(%)": ("Ordinary Margin", "%"), "ROE(%)": ("ROE", "%"),
    "ROA(%)": ("ROA", "%"), "DEレシオ(倍)": ("D/E Ratio", "x"),
    "ネット有利子負債(百万円)": ("Net Debt", "¥M"),
}
GRADE_COLOR = {"A": "#16a34a", "B": "#2563eb", "C": "#d97706",
               "D": "#dc2626", "判定不能": "#64748b"}


def _to_png_bytes(file_path: str) -> bytes:
    """Image or PDF (page 1) → PNG bytes."""
    if file_path.lower().endswith(".pdf"):
        pil = pdfium.PdfDocument(file_path)[0].render(scale=2.0).to_pil()
    else:
        pil = Image.open(file_path).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _fmt(v):
    return f"{v:,}" if isinstance(v, (int, float)) else "—"


def _security_html(local: bool, t_ext: float, t_sum: float) -> str:
    if local:
        return f"""
<div style="border:1px solid #16a34a;background:#f0fdf4;border-radius:12px;padding:14px 16px">
  <div style="font-size:15px;font-weight:700;color:#15803d">🔒 Secure — fully on-device</div>
  <div style="color:#166534;font-size:13px;margin-top:2px">
    No customer data left this machine. No external API was called.</div>
  <div style="color:#3f6212;font-size:12px;margin-top:8px;border-top:1px dashed #bbf7d0;padding-top:8px">
    ⚡ Extract {t_ext:.2f}s &nbsp;·&nbsp; Memo {t_sum:.2f}s &nbsp;·&nbsp;
    <b>Total {t_ext + t_sum:.2f}s</b> on local hardware</div>
</div>"""
    return """
<div style="border:1px solid #dc2626;background:#fef2f2;border-radius:12px;padding:14px 16px">
  <div style="font-size:15px;font-weight:700;color:#b91c1c">⚠ External endpoint configured</div>
  <div style="color:#991b1b;font-size:13px">Data may leave this machine — not for production use.</div>
</div>"""


def _rating_html(grade: dict) -> str:
    g = grade.get("格付け", "判定不能")
    score = grade.get("スコア") or "—"
    color = GRADE_COLOR.get(g, "#64748b")
    reasons = "".join(
        f"<li style='margin:2px 0'>{r}</li>" for r in grade.get("根拠", []))
    label = "Provisional Credit Rating" if g != "判定不能" else "Rating — Insufficient Data"
    return f"""
<div style="border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#fff">
  <div style="display:flex;align-items:center;gap:14px">
    <div style="min-width:64px;height:64px;border-radius:12px;background:{color};
                color:#fff;display:flex;align-items:center;justify-content:center;
                font-size:32px;font-weight:800">{g if len(g) == 1 else '?'}</div>
    <div>
      <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">{label}</div>
      <div style="font-size:20px;font-weight:700;color:#0f172a">Grade {g}
        <span style="font-size:14px;color:#64748b;font-weight:500">· score {score}</span></div>
    </div>
  </div>
  <ul style="margin:10px 0 0;padding-left:18px;color:#475569;font-size:13px">{reasons}</ul>
  <div style="font-size:11px;color:#94a3b8;margin-top:6px">
    Computed deterministically (temperature 0) — reproducible for audit.</div>
</div>"""


def _alerts_html(warnings: list) -> str:
    if not warnings:
        return """
<div style="border:1px solid #16a34a;background:#f0fdf4;border-radius:12px;padding:12px 16px">
  <span style="color:#15803d;font-weight:700">✓ Audit layer passed</span>
  <span style="color:#166534;font-size:13px"> — no accounting inconsistencies detected.</span>
</div>"""
    items = "".join(f"<li style='margin:3px 0'>{w}</li>" for w in warnings)
    return f"""
<div style="border:1px solid #dc2626;background:#fef2f2;border-radius:12px;padding:12px 16px">
  <div style="color:#b91c1c;font-weight:700">⚠ Audit layer flagged possible extraction errors</div>
  <ul style="margin:6px 0 0;padding-left:18px;color:#991b1b;font-size:13px">{items}</ul>
  <div style="font-size:11px;color:#b91c1c;margin-top:6px">
    The deterministic layer caught what the model got wrong — before it reached the officer.</div>
</div>"""


def _financials_html(data: dict, ratios: dict) -> str:
    def rows(keys):
        out = ""
        for k in keys:
            out += (f"<tr><td style='padding:4px 10px;color:#334155'>{FIELD_EN.get(k, k)}"
                    f"<span style='color:#94a3b8'> · {k}</span></td>"
                    f"<td style='padding:4px 10px;text-align:right;font-variant-numeric:tabular-nums;"
                    f"font-weight:600;color:#0f172a'>{_fmt(data.get(k))}</td></tr>")
        return out

    ratio_cells = ""
    for k, (en, unit) in RATIO_EN.items():
        if k in ratios:
            ratio_cells += (
                f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:6px 10px;background:#f8fafc'>"
                f"<div style='font-size:11px;color:#64748b'>{en}</div>"
                f"<div style='font-size:15px;font-weight:700;color:#0f172a'>"
                f"{_fmt(ratios[k])}<span style='font-size:11px;color:#64748b'> {unit}</span></div></div>")

    return f"""
<div style="border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#fff">
  <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
    Extracted figures <span style="text-transform:none">(¥ millions)</span></div>
  <div style="display:flex;gap:18px;flex-wrap:wrap">
    <table style="flex:1;min-width:230px;border-collapse:collapse;font-size:13px">
      <tr><td colspan="2" style="padding:2px 10px;font-weight:700;color:#475569">Income Statement</td></tr>
      {rows(PL_KEYS)}</table>
    <table style="flex:1;min-width:230px;border-collapse:collapse;font-size:13px">
      <tr><td colspan="2" style="padding:2px 10px;font-weight:700;color:#475569">Balance Sheet</td></tr>
      {rows(BS_KEYS)}</table>
  </div>
  <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin:12px 0 6px">
    Derived metrics</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px">
    {ratio_cells or "<span style='color:#94a3b8;font-size:13px'>No metrics computed.</span>"}
  </div>
</div>"""


def _error_card(msg: str) -> str:
    return (f"<div style='border:1px solid #dc2626;background:#fef2f2;border-radius:12px;"
            f"padding:14px 16px'><div style='color:#b91c1c;font-weight:700'>"
            f"⚠ Could not process this document</div>"
            f"<div style='color:#991b1b;font-size:13px;margin-top:4px'>{msg}</div></div>")


_NO_FIGURES = (
    "<div style='border:1px solid #d97706;background:#fffbeb;border-radius:12px;padding:14px 16px'>"
    "<div style='color:#b45309;font-weight:700'>⚠ No figures extracted</div>"
    "<div style='color:#92400e;font-size:13px;margin-top:4px'>"
    "The on-device 1.6B model couldn't read this layout (dense multi-column statement). "
    "This is the known capability gap — the fine-tune targets exactly these documents. "
    "Try the sample or a single-table statement.</div></div>")


# UIラベル → 抽出エンジン
ENGINE_MAP = {
    "Liquid VL · 1.6B (on-device, fast)": "liquid_vl",
    "Qwen-7B · local (reads complex docs)": "qwen_vl",
    "OCR + Liquid (EasyOCR)": "ocr",
}


def run(file_path, engine_label):
    if not file_path:
        return ("", "", "", "", "Upload a financial statement to begin.", "")
    engine = ENGINE_MAP.get(engine_label, "liquid_vl")
    try:
        img_bytes = _to_png_bytes(file_path)
        data, t_extract = extract_financials(img_bytes, engine)
        memo, t_summary, ratios, grade, warnings = risk_summary(data)
    except Exception as e:
        # モデルサーバ断・描画失敗など、何が起きてもUIは落とさない（デモ保護）
        return (_error_card(f"{type(e).__name__}: {e}"), "", "", "",
                "Processing failed — see the message on the left.", "")

    json_str = json.dumps({"extracted": data, "ratios": ratios},
                          ensure_ascii=False, indent=2)
    security = _security_html(is_local_only(), t_extract, t_summary)
    # 抽出が全滅 = 実機VLがこの実文書を読めなかった。クラッシュではなく明示する。
    if all(data.get(k) is None for k in FIELD_EN):
        return (security, _NO_FIGURES, "", _financials_html(data, ratios), memo, json_str)

    return (security, _rating_html(grade), _alerts_html(warnings),
            _financials_html(data, ratios), memo, json_str)


def load_sample():
    return make_sample()


HEADER = """
<div style="padding:6px 2px 2px">
  <div style="font-size:26px;font-weight:800;color:#0f172a">🏦 NeoBank AI</div>
  <div style="font-size:15px;color:#334155;font-weight:600">On-Premise Credit Underwriting Assistant</div>
  <div style="font-size:13px;color:#64748b;margin-top:4px;max-width:760px">
    Reads a Japanese financial statement and drafts a credit memo <b>entirely on-device</b>.
    Customer financials never leave the machine — the only architecture a regional bank's
    compliance desk can approve under APPI &amp; FISC.</div>
</div>"""

FOOTER = """
<div style="text-align:center;color:#94a3b8;font-size:12px;margin-top:10px">
  Powered by Liquid <b>LFM2.5-VL</b> + <b>LFM2.5-JP</b> · on-device via llama.cpp on AMD Ryzen AI
</div>"""

THEME = gr.themes.Soft(primary_hue="indigo", neutral_hue="slate")

with gr.Blocks(title="NeoBank AI — Credit Underwriting") as demo:
    gr.HTML(HEADER)
    with gr.Row():
        with gr.Column(scale=4):
            gr.Markdown("#### 1 · Upload statement")
            f = gr.File(label="Financial statement (image or PDF)",
                        file_types=[".png", ".jpg", ".jpeg", ".pdf"], type="filepath")
            engine = gr.Radio(
                choices=list(ENGINE_MAP.keys()),
                value="Liquid VL · 1.6B (on-device, fast)",
                label="Extraction engine",
                info="Liquid VL = small & fast (simple docs). Qwen-7B = local, reads dense real 短信. "
                     "All on-device; downstream analysis is always Liquid.")
            with gr.Row():
                btn = gr.Button("Generate credit memo", variant="primary", scale=2)
                sample_btn = gr.Button("Try sample", scale=1)
            security_out = gr.HTML()
        with gr.Column(scale=6):
            gr.Markdown("#### 2 · Analysis")
            rating_out = gr.HTML()
            alerts_out = gr.HTML()
            financials_out = gr.HTML()
            memo_out = gr.Textbox(label="Credit opinion — draft (Japanese)", lines=14)
            with gr.Accordion("Raw extracted JSON", open=False):
                json_out = gr.Code(language="json")
    gr.HTML(FOOTER)

    outputs = [security_out, rating_out, alerts_out, financials_out, memo_out, json_out]
    btn.click(run, inputs=[f, engine], outputs=outputs)
    sample_btn.click(load_sample, outputs=f)

if __name__ == "__main__":
    demo.launch(theme=THEME)
