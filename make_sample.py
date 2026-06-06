"""デモ用のサンプル決算書画像を生成する。
実顧客データは使わず、架空企業の数字（sample_data.py）を描画する。"""
import os

from PIL import Image, ImageDraw, ImageFont

from sample_data import SAMPLE_FINANCIALS, COMPANY_NAME

# 日本語を描画できるフォントを OS 横断で探す。
# 既定フォントは CJK 非対応で「豆腐□」になるため、必ず実在の日本語フォントを使う。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\YuGothM.ttc",          # Windows: 游ゴシック Medium
    r"C:\Windows\Fonts\meiryo.ttc",           # Windows: メイリオ
    r"C:\Windows\Fonts\msgothic.ttc",         # Windows: MS ゴシック
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",            # macOS
)


def _resolve_font_path():
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


_FONT_PATH = _resolve_font_path()


def _font(size):
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    # フォールバック（日本語は化けるので警告）。本番では _FONT_CANDIDATES を増やすこと。
    print("[make_sample] 警告: 日本語フォントが見つからず既定フォントで描画します（文字化けの可能性）")
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
