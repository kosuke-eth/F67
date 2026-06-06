import pypdfium2 as pdfium
from PIL import Image
import io
from llm_client import vl_extract
from extract import EXTRACT_PROMPT, parse_extraction

pdf = pdfium.PdfDocument("data/real_pdfs/lifeline_2025.pdf")
full = pdf[0].render(scale=3.0).to_pil()  # 高解像度で描画
W, H = full.size
print("full size:", full.size)

# 上部45%（連結経営成績＋財政状態のサマリー表）だけを切り出す
crop = full.crop((0, int(H * 0.10), W, int(H * 0.50)))
crop.save("data/real_pdfs/lifeline_crop.png")
print("crop size:", crop.size)

buf = io.BytesIO(); crop.save(buf, format="PNG")
raw, lat = vl_extract(buf.getvalue(), EXTRACT_PROMPT)
print(f"\n[crop 抽出 {lat:.2f}s]")
print("RAW:", raw[:500].replace(chr(10), " "))
