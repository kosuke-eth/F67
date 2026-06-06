"""NeoBank AI — On-Premise Credit Underwriting Assistant (Gradio UI).

Upload a Japanese financial statement (image / PDF) → on-device model extracts the
figures → a deterministic engine computes ratios, a provisional rating, and audit
checks → an on-device Japanese LFM drafts the credit opinion. Nothing leaves the machine.

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
from llm_client import is_local_only, jp_chat
from make_sample import make_sample
from qualitative import document_text, qualitative_summary
import context as ctx_ref

tracing.init(os.environ.get("WEAVE_PROJECT", "neobank-ai"))

# --- English labels alongside the Japanese source fields (content stays JP) ---
FIELD_EN = {
    "売上高": "Net Sales", "営業利益": "Operating Income", "経常利益": "Ordinary Income",
    "当期純利益": "Net Income", "総資産": "Total Assets", "純資産": "Net Assets",
    "有利子負債": "Interest-bearing Debt", "現預金": "Cash & Deposits",
}
PL_KEYS = ["売上高", "営業利益", "経常利益", "当期純利益"]
BS_KEYS = ["総資産", "純資産", "有利子負債", "現預金"]

# ratio key -> (English, unit, (good, ok)|None, higher_is_better|None, category)
RATIO_META = {
    "営業利益率(%)": ("Operating Margin", "%", (8, 3), True, "Profitability"),
    "経常利益率(%)": ("Ordinary Margin", "%", (8, 3), True, "Profitability"),
    "当期純利益率(%)": ("Net Margin", "%", (5, 2), True, "Profitability"),
    "ROE(%)": ("ROE", "%", (10, 5), True, "Profitability"),
    "ROA(%)": ("ROA", "%", (5, 2), True, "Profitability"),
    "売上高成長率(%)": ("Revenue Growth · YoY", "%", (5, 0), True, "Growth"),
    "営業利益成長率(%)": ("Op. Income Growth · YoY", "%", (5, 0), True, "Growth"),
    "自己資本比率(%)": ("Equity Ratio", "%", (40, 20), True, "Safety"),
    "DEレシオ(倍)": ("D/E Ratio", "x", (1.0, 2.0), False, "Safety"),
    "ネット有利子負債(百万円)": ("Net Debt", "¥M", None, None, "Safety"),
    "営業CFマージン(%)": ("Op. Cash-Flow Margin", "%", (8, 3), True, "Cash Flow & Debt"),
    "フリーCF(百万円)": ("Free Cash Flow", "¥M", None, None, "Cash Flow & Debt"),
    "債務償還年数(年)": ("Debt Repayment", "yr", (10, 20), False, "Cash Flow & Debt"),
    "営業CF対純利益(倍)": ("CF / Net Income", "x", (1.0, 0.7), True, "Cash Flow & Debt"),
    "借入余力目安(百万円)": ("Est. Debt Headroom", "¥M", None, None, "Cash Flow & Debt"),
}
CATEGORIES = ["Profitability", "Growth", "Safety", "Cash Flow & Debt"]
CF_EN = {"営業CF": "Operating CF", "投資CF": "Investing CF", "財務CF": "Financing CF"}
GRADE = {
    "A": ("#16a34a", "Strong", "優良"), "B": ("#2563eb", "Sound", "良好"),
    "C": ("#d97706", "Watch", "要注意"), "D": ("#dc2626", "Caution", "警戒"),
    "判定不能": ("#64748b", "Insufficient data", "判定不能"),
}
ENGINE_MAP = {
    "Liquid VL · 1.6B": "liquid_vl",
    "Qwen-7B · local": "qwen_vl",
}

CSS = """
/* Force a cohesive LIGHT banking palette regardless of the browser's dark mode
   by overriding Gradio's theme variables (so file upload / radio / code match the cards). */
.gradio-container, .gradio-container .dark {
  --body-background-fill:#eef2f6 !important;
  --background-fill-primary:#ffffff !important;
  --background-fill-secondary:#f8fafc !important;
  --block-background-fill:#ffffff !important;
  --block-border-color:#e2e8f0 !important;
  --border-color-primary:#e2e8f0 !important;
  --body-text-color:#0f172a !important;
  --body-text-color-subdued:#64748b !important;
  --input-background-fill:#ffffff !important;
  --block-label-text-color:#334155 !important;
  --neutral-50:#f8fafc !important; --neutral-100:#f1f5f9 !important; --neutral-200:#e2e8f0 !important;
}
.gradio-container {max-width:1180px !important; background:#eef2f6 !important; color:#0f172a;}
#nb-header {background:linear-gradient(100deg,#0f2747,#1e3a63); border-radius:14px;
  padding:18px 22px; color:#fff; margin-bottom:6px;}
#nb-header .brand {font-size:22px; font-weight:800; letter-spacing:.2px;}
#nb-header .tag {font-size:13px; color:#c7d6ec; margin-top:3px; max-width:720px;}
#nb-header .pill {float:right; background:#0c3b2e; border:1px solid #16a34a; color:#86efac;
  border-radius:999px; padding:6px 13px; font-size:12px; font-weight:700;}
.nb-sec {font-size:13px; font-weight:800; color:#1e3a63; text-transform:uppercase;
  letter-spacing:.06em; margin:6px 0 2px;}
.nb-card {background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px;
  margin-bottom:4px;}
.nb-label {font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.06em; font-weight:700;}
.nb-muted {color:#94a3b8; font-size:12px;}
.nb-ph {background:#fff; border:1px dashed #cbd5e1; border-radius:12px; padding:22px 16px;
  color:#94a3b8; font-size:13px; text-align:center;}
footer {display:none !important;}
"""

# Force light mode even if the browser/system prefers dark (banking apps read light).
HEAD = """<script>
(function(){var u=new URL(window.location);
if(u.searchParams.get('__theme')!=='light'){u.searchParams.set('__theme','light');
window.location.replace(u.toString());}})();
</script>"""


def _to_png_bytes(file_path: str) -> bytes:
    if file_path.lower().endswith(".pdf"):
        pil = pdfium.PdfDocument(file_path)[0].render(scale=2.0).to_pil()
    else:
        pil = Image.open(file_path).convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _fmt(v):
    return f"{v:,}" if isinstance(v, (int, float)) else "—"


def _ratio_tone(key, val):
    meta = RATIO_META.get(key)
    if not meta or meta[2] is None or not isinstance(val, (int, float)):
        return "#475569"
    good, ok = meta[2]
    higher = meta[3]
    if higher:
        return "#16a34a" if val >= good else "#d97706" if val >= ok else "#dc2626"
    return "#16a34a" if val <= good else "#d97706" if val <= ok else "#dc2626"


# ---------- HTML builders -----------------------------------------------------
HEADER = (
    "<div id='nb-header'>"
    "<span class='pill'>● On-device · data never leaves this machine</span>"
    "<div class='brand'>🏦 NeoBank&nbsp;AI</div>"
    "<div class='tag'>On-premise credit underwriting for Japanese regional banks. "
    "Reads a 決算書 and drafts an auditable credit memo — entirely on-device, the only "
    "architecture a 地銀 compliance desk can approve under APPI &amp; FISC.</div></div>"
)


def _status_html(local, t_ext, t_sum, engine_label):
    color, bg, txt = (("#16a34a", "#f0fdf4", "#15803d") if local
                      else ("#dc2626", "#fef2f2", "#b91c1c"))
    head = ("🔒 Secure — fully on-device" if local
            else "⚠ External endpoint configured")
    return (
        f"<div class='nb-card' style='border-color:{color};background:{bg}'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap'>"
        f"<div style='font-weight:800;color:{txt}'>{head}</div>"
        f"<div class='nb-muted'>engine: <b style='color:{txt}'>{engine_label}</b></div></div>"
        f"<div style='color:{txt};font-size:12px;margin-top:6px'>"
        f"⚡ Extract {t_ext:.2f}s · Memo {t_sum:.2f}s · <b>Total {t_ext + t_sum:.2f}s</b> "
        f"on local hardware · no external API called</div></div>")


def _rating_html(grade):
    g = grade.get("格付け", "判定不能")
    color, en, jp = GRADE.get(g, GRADE["判定不能"])
    score = grade.get("スコア") or "—"
    letter = g if len(g) == 1 else "?"
    reasons = "".join(f"<li style='margin:2px 0'>{r}</li>" for r in grade.get("根拠", []))
    return (
        f"<div class='nb-card'>"
        f"<div style='display:flex;gap:16px;align-items:center'>"
        f"<div style='min-width:74px;height:74px;border-radius:16px;background:{color};"
        f"color:#fff;display:flex;align-items:center;justify-content:center;"
        f"font-size:38px;font-weight:800;box-shadow:0 4px 12px {color}55'>{letter}</div>"
        f"<div><div class='nb-label'>Provisional Credit Rating</div>"
        f"<div style='font-size:22px;font-weight:800;color:#0f172a'>{en}"
        f"<span style='font-size:14px;color:#64748b;font-weight:600'> · {jp} · score {score}</span></div>"
        f"<div class='nb-muted'>Deterministic (temperature 0) — reproducible for audit</div></div></div>"
        f"<ul style='margin:10px 0 0;padding-left:18px;color:#475569;font-size:13px'>{reasons}</ul></div>")


def _ratio_card(k, val):
    en, unit, _, _, _ = RATIO_META[k]
    tone = _ratio_tone(k, val)
    return (f"<div style='border:1px solid #e2e8f0;border-left:4px solid {tone};"
            f"border-radius:8px;padding:8px 12px;background:#f8fafc'>"
            f"<div style='font-size:11px;color:#64748b'>{en}</div>"
            f"<div style='font-size:18px;font-weight:800;color:{tone}'>"
            f"{_fmt(val)}<span style='font-size:11px;color:#94a3b8;font-weight:600'> {unit}</span>"
            f"</div></div>")


def _ratios_html(ratios):
    sections = ""
    for cat in CATEGORIES:
        cards = "".join(_ratio_card(k, ratios[k]) for k, m in RATIO_META.items()
                        if m[4] == cat and k in ratios)
        if not cards:
            continue
        sections += (
            f"<div style='margin-bottom:10px'>"
            f"<div style='font-size:11px;font-weight:700;color:#1e3a63;margin-bottom:5px'>{cat}</div>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px'>"
            f"{cards}</div></div>")
    if not sections:
        sections = "<span class='nb-muted'>No metrics computed (insufficient figures).</span>"
    return (f"<div class='nb-card'><div class='nb-label' style='margin-bottom:8px'>"
            f"Credit analysis</div>{sections}</div>")


def _statement_html(data):
    labels = {**FIELD_EN, **CF_EN}

    def rows(keys):
        out = ""
        for k in keys:
            out += (f"<tr><td style='padding:5px 10px;color:#334155'>{labels.get(k, k)}"
                    f"<span class='nb-muted'> · {k}</span></td>"
                    f"<td style='padding:5px 10px;text-align:right;font-variant-numeric:tabular-nums;"
                    f"font-weight:700;color:#0f172a'>{_fmt(data.get(k))}</td></tr>")
        return out

    def table(title, keys):
        return (f"<table style='flex:1;min-width:230px;border-collapse:collapse;font-size:13px'>"
                f"<tr><td colspan=2 style='padding:3px 10px;font-weight:800;color:#1e3a63'>{title}</td></tr>"
                f"{rows(keys)}</table>")

    cf = table("Cash Flow", list(CF_EN)) if any(data.get(k) is not None for k in CF_EN) else ""
    return (
        f"<div class='nb-card'>"
        f"<div class='nb-label'>Extracted figures <span style='text-transform:none'>(¥ millions)</span></div>"
        f"<div style='display:flex;gap:20px;flex-wrap:wrap;margin-top:6px'>"
        f"{table('Income Statement', PL_KEYS)}{table('Balance Sheet', BS_KEYS)}{cf}</div></div>")


def _audit_html(warnings):
    if not warnings:
        return ("<div class='nb-card' style='border-color:#16a34a;background:#f0fdf4'>"
                "<span style='color:#15803d;font-weight:800'>✓ Audit layer passed</span>"
                "<span style='color:#166534;font-size:13px'> — no accounting inconsistencies. "
                "Every figure recomputed deterministically.</span></div>")
    items = "".join(f"<li style='margin:3px 0'>{w}</li>" for w in warnings)
    return (f"<div class='nb-card' style='border-color:#dc2626;background:#fef2f2'>"
            f"<div style='color:#b91c1c;font-weight:800'>⚠ Audit layer flagged possible extraction errors</div>"
            f"<ul style='margin:6px 0 4px;padding-left:18px;color:#991b1b;font-size:13px'>{items}</ul>"
            f"<div style='font-size:11px;color:#b91c1c'>The deterministic layer caught what the "
            f"model got wrong — before it reached the officer.</div></div>")


_NO_FIGURES = (
    "<div class='nb-card' style='border-color:#d97706;background:#fffbeb'>"
    "<div style='color:#b45309;font-weight:800'>⚠ No figures extracted</div>"
    "<div style='color:#92400e;font-size:13px;margin-top:4px'>This engine couldn't read the layout "
    "(dense multi-column statement). Switch the engine to <b>Qwen-7B · local</b>, or try the sample "
    "/ a single-table statement.</div></div>")


def _memo_html(memo):
    body = (memo or "").replace("\n", "<br>")
    return (f"<div class='nb-card'><div class='nb-label'>Credit opinion — AI draft (Japanese)</div>"
            f"<div style='margin-top:8px;font-size:13.5px;line-height:1.7;color:#1f2937'>{body}</div>"
            f"<div class='nb-muted' style='margin-top:10px;border-top:1px dashed #e2e8f0;padding-top:8px'>"
            f"Draft for the underwriter — not a lending decision. Figures are deterministic and auditable.</div></div>")


def _qualitative_html(summary):
    if not summary:
        return ("<div class='nb-card nb-muted'>Qualitative analysis reads the filing's narrative "
                "sections — business overview, disclosed risks, outlook. Available for PDF filings "
                "(the demo PDFs work).</div>")
    body = summary.replace("\n", "<br>")
    return (f"<div class='nb-card'><div class='nb-label'>Qualitative analysis — narrative risk read "
            f"<span style='text-transform:none;font-weight:500;color:#94a3b8'>(on-device Liquid, from "
            f"the filing text)</span></div>"
            f"<div style='margin-top:8px;font-size:13.5px;line-height:1.7;color:#1f2937'>{body}</div></div>")


def _context_html(bench, tr):
    """業界ベンチマーク + 多年度トレンド（ローカル参照データから）。"""
    cards = ""
    if bench and bench["rows"]:
        rws = ""
        for r in bench["rows"]:
            meta = RATIO_META.get(r["key"])
            if not meta:
                continue
            en, unit, higher = meta[0], meta[1], meta[3]
            v, m = r["value"], r["median"]
            better = (v >= m) if higher else (v <= m)
            color = "#16a34a" if better else "#d97706"
            tag = "▲ above median" if v >= m else "▼ below median"
            rws += (f"<tr><td style='padding:4px 10px'>{en}</td>"
                    f"<td style='padding:4px 10px;text-align:right;font-weight:700;color:{color}'>{_fmt(v)}{unit}</td>"
                    f"<td style='padding:4px 10px;text-align:right;color:#64748b'>{_fmt(m)}{unit}</td>"
                    f"<td style='padding:4px 10px;color:{color};font-size:12px'>{tag}</td></tr>")
        cards += (f"<div class='nb-card'><div class='nb-label'>Industry benchmark — {bench['company']} "
                  f"<span style='text-transform:none;color:#64748b'>vs 「{bench['industry']}」 sector median "
                  f"(n={bench['n']})</span></div>"
                  f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:6px'>"
                  f"<tr style='color:#64748b;font-size:11px'><td style='padding:2px 10px'>Metric</td>"
                  f"<td style='padding:2px 10px;text-align:right'>Company</td>"
                  f"<td style='padding:2px 10px;text-align:right'>Sector median</td><td></td></tr>"
                  f"{rws}</table></div>")
    if tr and len(tr) >= 2:
        head = "".join(f"<td style='padding:2px 8px;text-align:right;color:#64748b;font-size:11px'>"
                       f"FY{y.get('fiscal_year')}</td>" for y in tr)

        def frow(label, key, unit=""):
            cells = "".join(f"<td style='padding:4px 8px;text-align:right;"
                            f"font-variant-numeric:tabular-nums'>{_fmt(y.get(key))}{unit}</td>" for y in tr)
            return f"<tr><td style='padding:4px 10px;color:#334155'>{label}</td>{cells}</tr>"

        def rrow(label, key, unit=""):
            cells = "".join(f"<td style='padding:4px 8px;text-align:right'>"
                            f"{_fmt((y.get('ratios') or {}).get(key))}{unit}</td>" for y in tr)
            return f"<tr><td style='padding:4px 10px;color:#334155'>{label}</td>{cells}</tr>"

        cards += (f"<div class='nb-card'><div class='nb-label'>Multi-year trend "
                  f"<span style='text-transform:none;color:#64748b'>(¥M / %)</span></div>"
                  f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:6px'>"
                  f"<tr><td></td>{head}</tr>"
                  f"{frow('Net Sales', '売上高')}{frow('Operating Income', '営業利益')}"
                  f"{frow('Net Assets', '純資産')}{rrow('Equity Ratio', '自己資本比率(%)', '%')}"
                  f"{rrow('Op. Margin', '営業利益率(%)', '%')}</table></div>")
    if not cards:
        return ("<div class='nb-card nb-muted'>Trend &amp; peer benchmark is available for listed companies "
                "matched in the local reference (by 証券コード). For unlisted / SME documents, peer data isn't "
                "available — rely on the on-device ratios + qualitative read above.</div>")
    return cards


def _build_ctx(data, ratios, grade, warnings, qual, doc_txt, bench):
    """与信コパイロットのグラウンディング文脈（数値＋指標＋格付け＋定性＋本文＋業界比較）。"""
    parts = [
        "【財務数値】" + json.dumps({k: v for k, v in data.items() if v is not None}, ensure_ascii=False),
        "【算出指標】" + json.dumps(ratios, ensure_ascii=False),
        "【暫定格付け】" + json.dumps(grade, ensure_ascii=False),
        "【整合性アラート】" + json.dumps(warnings, ensure_ascii=False),
    ]
    if bench and bench.get("rows"):
        b = {r["key"]: {"自社": r["value"], "業種中央値": r["median"]} for r in bench["rows"]}
        parts.append(f"【業界ベンチマーク（{bench['industry']}, n={bench['n']}）】" +
                     json.dumps(b, ensure_ascii=False))
    if qual:
        parts.append("【定性情報の要約】\n" + qual)
    if doc_txt:
        parts.append("【書類本文の抜粋】\n" + doc_txt[:2500])
    return "\n\n".join(parts)


def _error_card(msg):
    return (f"<div class='nb-card' style='border-color:#dc2626;background:#fef2f2'>"
            f"<div style='color:#b91c1c;font-weight:800'>⚠ Could not process this document</div>"
            f"<div style='color:#991b1b;font-size:13px;margin-top:4px'>{msg}</div></div>")


# ---------- callbacks ---------------------------------------------------------
ASSISTANT_SYSTEM = (
    "あなたは地方銀行の融資担当者を補助する与信分析アシスタントです。"
    "提供された【分析データ】（抽出済み財務数値・算出指標・暫定格付け・整合性アラート）のみに基づき、"
    "日本語で簡潔かつ正確に回答してください。データに無い事項は推測せず『データにありません』と述べます。"
    "数値に言及する際は該当する指標名と値を引用します。断定的な融資可否の結論は述べません。"
    "すべて端末内で処理され、顧客データは外部に送信されません。"
)


def run(file_path, engine_label):
    # order: status, rating, ratios, audit, statement, qualitative, context, memo, json, ctx
    if not file_path:
        return ("<div class='nb-card nb-muted'>Upload a financial statement, choose an engine, "
                "then click <b>Run analysis</b>.</div>", "", "", "", "", "", "", "", "", "")
    engine = ENGINE_MAP.get(engine_label, "liquid_vl")
    try:
        img = _to_png_bytes(file_path)
        data, t_ext = extract_financials(img, engine)
        memo, t_sum, ratios, grade, warnings = risk_summary(data)
        doc_txt = document_text(file_path)
        qual, t_qual = qualitative_summary(doc_txt)
    except Exception as e:
        return (_error_card(f"{type(e).__name__}: {e}"), "", "", "", "", "", "",
                _memo_html("Processing failed — see the message above."), "", "")

    js = json.dumps({"engine": engine, "extracted": data, "ratios": ratios},
                    ensure_ascii=False, indent=2)
    status = _status_html(is_local_only(), t_ext, t_sum + t_qual, engine_label)
    qual_html = _qualitative_html(qual)
    sec = data.get("証券コード")
    bench = ctx_ref.benchmark(sec, ratios)
    context_html = _context_html(bench, ctx_ref.trend(sec))
    if all(data.get(k) is None for k in FIELD_EN):
        return (status, _NO_FIGURES, "", "", _statement_html(data), qual_html,
                context_html, _memo_html(memo), js, "")
    cctx = _build_ctx(data, ratios, grade, warnings, qual, doc_txt, bench)
    return (status, _rating_html(grade), _ratios_html(ratios), _audit_html(warnings),
            _statement_html(data), qual_html, context_html, _memo_html(memo), js, cctx)


def respond(message, history, ctx):
    """与信アシスタントへの追問。抽出済みデータに限定して回答（グラウンディング）。"""
    history = history or []
    message = (message or "").strip()
    if not message:
        return "", history
    if not ctx:
        reply = "まず決算書をアップロードして『Run analysis』を実行してください。その後、本分析について質問できます。"
    else:
        msgs = [{"role": "system", "content": ASSISTANT_SYSTEM + "\n\n【分析データ】\n" + ctx}]
        msgs += [{"role": t["role"], "content": t["content"]} for t in history]
        msgs.append({"role": "user", "content": message})
        try:
            reply, _ = jp_chat(msgs)
        except Exception as e:
            reply = f"（アシスタントエラー: {e}）"
    history = history + [{"role": "user", "content": message},
                         {"role": "assistant", "content": reply}]
    return "", history


def load_sample():
    return make_sample()


def load_lifeline():
    p = os.path.join("data", "real_pdfs", "lifeline_2025.pdf")
    return p if os.path.exists(p) else None


_PH = ("<div class='nb-ph'>Awaiting analysis — load a statement, pick an engine, "
       "then click <b>Run analysis</b>.</div>")

with gr.Blocks(title="NeoBank AI — Credit Underwriting") as demo:
    gr.HTML(HEADER)
    ctx_state = gr.State("")
    with gr.Row():
        with gr.Column(scale=4):
            gr.HTML("<div class='nb-sec'>1 · Statement</div>")
            with gr.Group():
                f = gr.File(label="Financial statement (image or PDF)",
                            file_types=[".png", ".jpg", ".jpeg", ".pdf"], type="filepath")
                with gr.Row():
                    sample_btn = gr.Button("📄 Load sample", size="sm")
                    real_btn = gr.Button("🏢 Load real 短信", size="sm")
                gr.HTML("<div class='nb-muted'>Demo shortcuts — or drop your own file above.</div>")
                engine = gr.Radio(
                    choices=list(ENGINE_MAP.keys()), value="Liquid VL · 1.6B",
                    label="Extraction engine",
                    info="Liquid VL = small & fast (simple docs). Qwen-7B = local, reads dense "
                         "real 短信. Both on-device; analysis is always Liquid.")
                btn = gr.Button("▶  Run analysis", variant="primary", size="lg")
            status_out = gr.HTML()
        with gr.Column(scale=6):
            gr.HTML("<div class='nb-sec'>2 · Underwriting analysis</div>")
            with gr.Tabs():
                with gr.Tab("📊 Overview"):
                    rating_out = gr.HTML(_PH)
                    ratios_out = gr.HTML()
                    audit_out = gr.HTML()
                with gr.Tab("📑 Financials"):
                    statement_out = gr.HTML()
                    with gr.Accordion("Raw extracted JSON", open=False):
                        json_out = gr.Code(language="json")
                    gr.HTML("<div class='nb-muted' style='margin:4px 2px'>Extracts P/L, balance sheet, "
                            "cash-flow &amp; prior-year figures, then computes a full credit-analysis "
                            "suite — all on-device and auditable.</div>")
                with gr.Tab("📈 Trend & Peers"):
                    context_out = gr.HTML()
                    gr.HTML("<div class='nb-muted' style='margin:4px 2px'>Industry median &amp; multi-year "
                            "trend from a <b>local</b> reference of ~500 EDINET companies — no network call.</div>")
                with gr.Tab("📝 Qualitative & Memo"):
                    qualitative_out = gr.HTML()
                    memo_out = gr.HTML()
                with gr.Tab("💬 Ask the analyst"):
                    gr.HTML("<div class='nb-muted' style='margin-bottom:4px'>On-device Liquid LFM · "
                            "answers only from the extracted figures + the filing text.</div>")
                    chatbot = gr.Chatbot(height=340, show_label=False)
                    with gr.Row():
                        msg = gr.Textbox(show_label=False, container=False, scale=8,
                                         placeholder="例: なぜこの暫定格付け？ / 返済能力は？ / 開示されたリスクは？")
                        send = gr.Button("Ask", variant="primary", scale=1, min_width=96)
                    gr.Examples(
                        ["この企業の返済能力をどう評価しますか？", "なぜこの暫定格付けなのですか？",
                         "経営陣はどんなリスクを開示していますか？", "融資にあたり追加で確認すべき点は？",
                         "前年比で何が変化しましたか？"],
                        inputs=msg, label="Suggested questions")

    btn.click(run, inputs=[f, engine],
              outputs=[status_out, rating_out, ratios_out, audit_out, statement_out,
                       qualitative_out, context_out, memo_out, json_out, ctx_state])
    sample_btn.click(load_sample, outputs=f)
    real_btn.click(load_lifeline, outputs=f)
    send.click(respond, [msg, chatbot, ctx_state], [msg, chatbot])
    msg.submit(respond, [msg, chatbot, ctx_state], [msg, chatbot])

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"),
                css=CSS, head=HEAD)
