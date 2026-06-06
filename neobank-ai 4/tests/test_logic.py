"""決定的ロジックのテスト（モデル不要）。実行: pytest -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import parse_extraction, _coerce_int
from summarize import compute_ratios


def test_coerce_int_variants():
    assert _coerce_int("1,234") == 1234
    assert _coerce_int("8420百万円") == 8420
    assert _coerce_int(512) == 512
    assert _coerce_int("該当なし") is None
    assert _coerce_int(None) is None


def test_parse_extraction_strips_codeblock_and_normalizes():
    raw = '```json\n{"売上高": "8,420", "営業利益": "512", "決算期": "2025年3月期"}\n```'
    data = parse_extraction(raw)
    assert data["売上高"] == 8420
    assert data["営業利益"] == 512
    assert data["決算期"] == "2025年3月期"


def test_parse_extraction_raises_without_json():
    try:
        parse_extraction("数字は読み取れませんでした")
        assert False, "should raise"
    except ValueError:
        pass


def test_compute_ratios():
    data = {"売上高": 8420, "営業利益": 512, "純資産": 2710,
            "総資産": 9870, "有利子負債": 3950, "現預金": 1180}
    r = compute_ratios(data)
    assert r["自己資本比率(%)"] == 27.5
    assert r["営業利益率(%)"] == 6.1
    assert r["DEレシオ(倍)"] == 1.46
    assert r["ネット有利子負債(百万円)"] == 2770


def test_compute_ratios_handles_missing():
    r = compute_ratios({"売上高": None, "総資産": 0})
    assert "自己資本比率(%)" not in r  # 0除算・None で落ちない
