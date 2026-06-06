import io, sys
import pypdfium2 as pdfium
from ocr_engine import ocr_rows
from extract import _parse_ocr_text

GOLD = {
    "lifeline": "売上56610 営業12326 経常12335 純利益9317 総資産75123 純資産59914 現預金11014",
    "capcom":   "(unknown gold — eyeball)",
}
name = sys.argv[1] if len(sys.argv) > 1 else "lifeline"
pdf = pdfium.PdfDocument(f"data/real_pdfs/{name}_2025.pdf")
img = pdf[0].render(scale=2.5).to_pil()
buf = io.BytesIO(); img.save(buf, format="PNG")

print(f"GOLD: {GOLD.get(name)}")
text, t_ocr = ocr_rows(buf.getvalue())
print(f"\n=== OCR rows ({t_ocr:.2f}s) — first 1200 chars ===")
print(text[:1200])
data, t = _parse_ocr_text(text, t_ocr)
print(f"\n=== Liquid parsed ({t:.2f}s total) ===")
for k, v in data.items():
    print(f"  {k}: {v}")
