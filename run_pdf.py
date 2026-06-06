"""実在の決算短信PDF（複数ページ可）でパイプラインを実行する確認用ドライバ。
    python run_pdf.py data/real_pdfs/lifeline_2025.pdf [page]
"""
import sys

from app import _to_png_bytes
from extract import extract_financials
from summarize import risk_summary

path = sys.argv[1]
img = _to_png_bytes(path)  # PDF1ページ目 or 画像 → PNG
data, t1 = extract_financials(img)
memo, t2, ratios, grade, warnings = risk_summary(data)

print(f"=== {path} ===")
print(f"[抽出 {t1:.2f}s]")
for k, v in data.items():
    print(f"  {k}: {v}")
print(f"\n[指標] {ratios}")
print(f"[格付け] {grade.get('格付け')}（{grade.get('スコア')}）")
if warnings:
    print("[整合性アラート]")
    for w in warnings:
        print("  -", w)
print(f"\n[所見 {t2:.2f}s]\n{memo}")
