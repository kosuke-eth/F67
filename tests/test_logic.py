"""決定的ロジックのテスト（モデル不要）。実行: pytest -q"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import parse_extraction, _coerce_int, normalize_schema
from summarize import compute_ratios, validate_financials, risk_grade


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


def test_compute_ratios_extended():
    data = {"売上高": 8420, "経常利益": 486, "当期純利益": 305,
            "純資産": 2710, "総資産": 9870}
    r = compute_ratios(data)
    assert r["経常利益率(%)"] == 5.8   # 486/8420
    assert r["ROE(%)"] == 11.3        # 305/2710
    assert r["ROA(%)"] == 3.1         # 305/9870


def test_normalize_schema_fills_and_drops():
    data = normalize_schema({"売上高": "8,420", "謎キー": 999})
    assert data["売上高"] == 8420
    assert data["総資産"] is None      # 欠損は null 補完
    assert "謎キー" not in data        # 余分なキーは捨てる


def test_validate_financials_flags_impossible():
    # 純資産 > 総資産 / 現預金 > 総資産 は抽出ミス
    w = validate_financials({"総資産": 100, "純資産": 500, "現預金": 300})
    assert any("純資産" in m for m in w)
    assert any("現預金" in m for m in w)
    # 整合的なデータなら警告なし
    assert validate_financials({"総資産": 9870, "純資産": 2710, "現預金": 1180}) == []


def test_validate_financials_flags_profit_over_sales():
    # 実機VLが観測した事故の再現: 営業利益に総資産の値(9870)を誤割当 → 売上高(8420)超え。
    # 決定的レイヤがこれを必ず捕捉し、117%の営業利益率が素通りしないことを保証する。
    w = validate_financials({"売上高": 8420, "営業利益": 9870, "総資産": 9710})
    assert any("営業利益" in m and "売上高" in m for m in w)
    # 正常な損益（利益 < 売上）なら警告なし
    assert validate_financials({"売上高": 8420, "営業利益": 512}) == []


def test_risk_grade_deterministic():
    strong = risk_grade({"自己資本比率(%)": 45, "DEレシオ(倍)": 0.8, "営業利益率(%)": 10})
    assert strong["格付け"] == "A"
    assert strong["スコア"] == "6/6"
    weak = risk_grade({"自己資本比率(%)": 10, "DEレシオ(倍)": 3.0, "営業利益率(%)": 1})
    assert weak["格付け"] == "D"
    # 指標欠如は判定不能（満点も減る）
    assert risk_grade({})["格付け"] == "判定不能"
