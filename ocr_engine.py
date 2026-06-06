"""ローカルOCRエンジン（EasyOCR）で決算書画像 → 行構造を保った素テキスト。

VL に OCR させると崩れる/ループするため、専用OCRで画素→文字を確実に取り、
レイアウト（行）を bbox から復元する。後段の項目抽出は Liquid のテキストモデルが担当。
すべてローカル実行（torchはCPU/GPU）。外部送信なし。
"""
import io
import os
import time

import numpy as np
from PIL import Image

_reader = None


def _get_reader():
    """EasyOCR Reader を遅延初期化（torch ロードを import 時に強制しない）。"""
    global _reader
    if _reader is None:
        import easyocr
        gpu = os.environ.get("OCR_GPU", "0") == "1"
        _reader = easyocr.Reader(["ja", "en"], gpu=gpu)
    return _reader


def ocr_rows(image_bytes: bytes):
    """画像 → 行ごとにまとめた素テキスト と OCRレイテンシ。
    bbox の y で行をクラスタリングし、各行を x 昇順で連結する。"""
    reader = _get_reader()
    img = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    t0 = time.perf_counter()
    dets = reader.readtext(img)  # [(bbox, text, conf), ...]
    latency = time.perf_counter() - t0

    items = []
    heights = []
    for bbox, text, conf in dets:
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        cy = sum(ys) / 4.0
        cx = sum(xs) / 4.0
        items.append((cy, cx, text))
        heights.append(max(ys) - min(ys))
    if not items:
        return "", latency

    # 行クラスタの閾値は文字高の中央値の6割（解像度非依存）
    med_h = sorted(heights)[len(heights) // 2] if heights else 16
    thr = max(8.0, med_h * 0.6)

    items.sort(key=lambda t: t[0])
    rows, cur, last_y = [], [], None
    for cy, cx, text in items:
        if last_y is None or abs(cy - last_y) <= thr:
            cur.append((cx, text))
        else:
            rows.append(cur)
            cur = [(cx, text)]
        last_y = cy
    if cur:
        rows.append(cur)

    lines = []
    for row in rows:
        row.sort(key=lambda t: t[0])
        lines.append("  ".join(t for _, t in row))
    return "\n".join(lines), latency
