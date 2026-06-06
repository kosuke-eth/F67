"""業界ベンチマーク + 多年度トレンド。ローカル参照データ(data/reference/*.json)のみを読む。
デモ実行時はネットに出ない（オンデバイスのまま）。参照が無い/未収載なら None を返す（UIは graceful）。"""
import json
from pathlib import Path

_REF = Path(__file__).with_name("data") / "reference"
_companies = None
_medians = None


def _load():
    global _companies, _medians
    if _companies is None:
        try:
            _companies = json.loads((_REF / "companies.json").read_text(encoding="utf-8"))
        except Exception:
            _companies = {}
    if _medians is None:
        try:
            _medians = json.loads((_REF / "sector_medians.json").read_text(encoding="utf-8"))
        except Exception:
            _medians = {}
    return _companies, _medians


def _norm(code):
    if code is None:
        return None
    s = str(code).strip()
    if len(s) == 5 and s.endswith("0"):
        return s[:4]
    return s


def benchmark(sec_code, ratios):
    """会社の指標 vs 業種中央値。{industry, n, company, rows:[{key,value,median}]} or None。"""
    companies, medians = _load()
    sec = _norm(sec_code)
    if not sec or sec not in companies:
        return None
    industry = companies[sec].get("industry")
    med = medians.get(industry, {}).get("medians", {})
    if not med:
        return None
    rows = [{"key": k, "value": ratios[k], "median": m}
            for k, m in med.items() if isinstance(ratios.get(k), (int, float))]
    return {"industry": industry, "n": medians[industry].get("n"),
            "company": companies[sec].get("name"), "rows": rows}


def trend(sec_code):
    """会社の多年度データ list（古い順）。or None。"""
    companies, _ = _load()
    sec = _norm(sec_code)
    if not sec or sec not in companies:
        return None
    return companies[sec].get("years")
