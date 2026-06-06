"""オラクル比較: 指定したVLエンドポイントで「実物の決算短信」を抽出させ、素の出力を見る。
LFM(8080) と Qwen-7B(8082) を同じ入力で比べ、「大きいモデルなら実文書の表を読めるのか」を判定する。

    # LFM(既定 8080)
    python oracle_test.py
    # Qwen(8082) を見る
    $env:VL_BASE_URL="http://127.0.0.1:8082/v1"; $env:VL_MODEL="qwen2.5-vl"; python oracle_test.py
"""
import io

import pypdfium2 as pdfium

from llm_client import vl_extract, VL_BASE_URL, VL_MODEL
from extract import EXTRACT_PROMPT, parse_extraction

PDF = "data/real_pdfs/lifeline_2025.pdf"
# 目視の正解（クロップ画像より）: 売上高56,610 営業利益12,326 当期純利益9,317 ほか
GOLD_HINT = "売上高56,610 / 営業利益12,326 / 当期純利益9,317（単位:百万円）"


def _png(pil):
    buf = io.BytesIO(); pil.save(buf, format="PNG"); return buf.getvalue()


def run(label, img_bytes):
    raw, lat = vl_extract(img_bytes, EXTRACT_PROMPT)
    print(f"\n--- {label}  ({lat:.2f}s) ---")
    print("RAW:", raw[:600].replace(chr(10), " "))
    try:
        print("PARSED:", {k: v for k, v in parse_extraction(raw).items() if v is not None})
    except Exception as e:
        print("PARSE FAIL:", e)


def main():
    print(f"endpoint: {VL_BASE_URL}  model: {VL_MODEL}")
    print(f"正解(目視): {GOLD_HINT}")
    full = pdfium.PdfDocument(PDF)[0].render(scale=3.0).to_pil()
    W, H = full.size
    crop = full.crop((0, int(H * 0.10), W, int(H * 0.50)))
    run("FULL PAGE", _png(full))
    run("CROP (経営成績+財政状態)", _png(crop))


if __name__ == "__main__":
    main()
