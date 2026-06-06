"""デモ用のサンプル決算書画像を生成する。
実顧客データは使わず、架空企業の数字（sample_data.py）を描画する。"""
from PIL import Image, ImageDraw, ImageFont

from sample_data import SAMPLE_FINANCIALS, COMPANY_NAME

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except Exception:
        return ImageFont.load_default()


def make_sample(path="sample_statement.png"):
    W, H = 760, 560
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    d.text((40, 30), f"{COMPANY_NAME}", font=_font(26), fill="black")
    d.text((40, 72), f"決算報告書  {SAMPLE_FINANCIALS['決算期']}", font=_font(18), fill="black")
    d.line((40, 108, W - 40, 108), fill="black", width=2)
    d.text((40, 120), "（単位：百万円）", font=_font(14), fill="gray")

    rows = [
        ("売上高", SAMPLE_FINANCIALS["売上高"]),
        ("営業利益", SAMPLE_FINANCIALS["営業利益"]),
        ("経常利益", SAMPLE_FINANCIALS["経常利益"]),
        ("当期純利益", SAMPLE_FINANCIALS["当期純利益"]),
        ("総資産", SAMPLE_FINANCIALS["総資産"]),
        ("純資産", SAMPLE_FINANCIALS["純資産"]),
        ("有利子負債", SAMPLE_FINANCIALS["有利子負債"]),
        ("現預金", SAMPLE_FINANCIALS["現預金"]),
    ]
    y = 160
    for label, val in rows:
        d.text((60, y), label, font=_font(18), fill="black")
        d.text((420, y), f"{val:,}", font=_font(18), fill="black")
        d.line((60, y + 34, W - 60, y + 34), fill="#cccccc", width=1)
        y += 48

    img.save(path)
    print(f"wrote {path}")
    return path


if __name__ == "__main__":
    make_sample()
