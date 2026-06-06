"""正解データ（gold JSON）→ 決算書スタイルの画像。抽出ベンチ＆ファインチューニング用。

実物の決算書に寄せた複数レイアウトでVL抽出を“揺らして”試す。特に template=2 は
前期/当期の2列にして、過去に観測した「営業利益に別行の値を誤割当」する事故を誘発・検出する。
"""
import random

from PIL import Image, ImageDraw

from make_sample import _font  # OS横断の日本語フォント解決を再利用

PL_FIELDS = ["売上高", "営業利益", "経常利益", "当期純利益"]
BS_FIELDS = ["総資産", "純資産", "有利子負債", "現預金"]


def _fmt(v):
    return f"{v:,}" if isinstance(v, (int, float)) else "―"


def _row(d, label, val, x_label=60, x_val=430, font_sz=18):
    d.text((x_label, _row.y), label, font=_font(font_sz), fill="black")
    d.text((x_val, _row.y), _fmt(val), font=_font(font_sz), fill="black")
    d.line((x_label, _row.y + 30, 700, _row.y + 30), fill="#cccccc", width=1)
    _row.y += 44


def _header(d, company, fy, subtitle):
    d.text((40, 28), company, font=_font(24), fill="black")
    d.text((40, 68), f"{subtitle}  {fy}", font=_font(16), fill="black")
    d.line((40, 100, 720, 100), fill="black", width=2)
    d.text((40, 110), "（単位：百万円）", font=_font(13), fill="gray")


def _flat(img, fin, company, fy):
    """template 0: 単純な一覧表。"""
    d = ImageDraw.Draw(img)
    _header(d, company, fy, "決算報告書")
    _row.y = 150
    for k in PL_FIELDS + BS_FIELDS:
        _row(d, k, fin.get(k))


def _sectioned(img, fin, company, fy):
    """template 1: 損益計算書 / 貸借対照表 の2セクション。"""
    d = ImageDraw.Draw(img)
    _header(d, company, fy, "決算報告書")
    _row.y = 145
    d.text((45, _row.y), "■ 損益計算書", font=_font(17), fill="#003366"); _row.y += 34
    for k in PL_FIELDS:
        _row(d, k, fin.get(k))
    _row.y += 10
    d.text((45, _row.y), "■ 貸借対照表", font=_font(17), fill="#003366"); _row.y += 34
    for k in BS_FIELDS:
        _row(d, k, fin.get(k))


def _two_period(img, fin, company, fy):
    """template 2: 前期/当期の2列（前期はダミー）。行ズレ耐性を試す難問。"""
    d = ImageDraw.Draw(img)
    _header(d, company, fy, "決算報告書（比較）")
    _row.y = 150
    d.text((430, _row.y - 36), "前期", font=_font(14), fill="gray")
    d.text((560, _row.y - 36), "当期", font=_font(14), fill="gray")
    for k in PL_FIELDS + BS_FIELDS:
        cur = fin.get(k)
        prev = int(cur * random.uniform(0.85, 1.12)) if isinstance(cur, (int, float)) else None
        d.text((60, _row.y), k, font=_font(17), fill="black")
        d.text((430, _row.y), _fmt(prev), font=_font(16), fill="#888888")  # 前期=ダミー
        d.text((560, _row.y), _fmt(cur), font=_font(16), fill="black")     # 当期=正解
        d.line((60, _row.y + 30, 700, _row.y + 30), fill="#cccccc", width=1)
        _row.y += 44


TEMPLATES = [_flat, _sectioned, _two_period]


def render_statement(fin: dict, company: str, fiscal_year, path: str,
                     template: int = 0, seed: int | None = None) -> str:
    """gold の財務数値を決算書画像にする。template で見た目を変える。"""
    if seed is not None:
        random.seed(seed)
    img = Image.new("RGB", (760, 620), "white")
    TEMPLATES[template % len(TEMPLATES)](img, fin, company or "サンプル株式会社", fiscal_year or "")
    img.save(path)
    return path
