"""EDINET DB から『業界ベンチマーク + 多年度トレンド』のローカル参照データを一括生成する。

これを一度作っておけば、デモ実行時はネットに出ずに（＝オンデバイスのまま）
「業界中央値との比較」「過去N年のトレンド」を出せる。顧客データは送らない。

    python build_reference.py --sample 500       # 500社サンプル + デモ企業を取得

出力:
  data/reference/companies.json      … 証券コード→{社名, 業種, 年度別の主要数値・指標}
  data/reference/sector_medians.json … 業種→主要指標の中央値
"""
import argparse
import json
import os
import statistics
from pathlib import Path

import requests

from download_models import _load_env
from summarize import compute_ratios

BASE = "https://edinetdb.jp/v1"
# デモ用PDFの証券コード（必ず参照データに含める）: lifeline, 明治, カプコン, エディオン, 大気社
DEMO_SEC = ["7575", "2269", "9697", "2730", "1979"]
BENCH_RATIOS = ["自己資本比率(%)", "営業利益率(%)", "経常利益率(%)", "当期純利益率(%)",
                "ROE(%)", "ROA(%)", "DEレシオ(倍)", "営業CFマージン(%)", "債務償還年数(年)"]


def _headers():
    _load_env(Path(__file__).with_name(".env"))
    k = os.environ.get("EDINETDB_API_KEY")
    if not k:
        raise SystemExit("EDINETDB_API_KEY が未設定です（.env）")
    return {"X-API-Key": k}


def _norm_sec(code):
    """EDINET DB の5桁 sec_code（例 75750）を 決算書の4桁（7575）に正規化。"""
    if not code:
        return None
    s = str(code).strip()
    if len(s) == 5 and s.endswith("0"):
        return s[:4]
    return s


def _row_schema(row):
    """EDINET DB の財務行（円）→ アプリのスキーマ（百万円）。compute_ratios と整合。"""
    def m(k):
        v = row.get(k)
        return int(round(v / 1_000_000)) if isinstance(v, (int, float)) else None
    ibd_c, ibd_n = row.get("ibd_current"), row.get("ibd_noncurrent")
    ibd = None
    if isinstance(ibd_c, (int, float)) or isinstance(ibd_n, (int, float)):
        ibd = int(round(((ibd_c or 0) + (ibd_n or 0)) / 1_000_000))
    return {"売上高": m("revenue"), "営業利益": m("operating_income"),
            "経常利益": m("ordinary_income"), "当期純利益": m("net_income"),
            "総資産": m("total_assets"), "純資産": m("net_assets"),
            "有利子負債": ibd, "現預金": m("cash"),
            "営業CF": m("cf_operating"), "投資CF": m("cf_investing")}


def company_index(headers, want):
    """/companies をページング（page/per_page 方式）で取得。全社（~3800）から探すため多めに。"""
    out, page = [], 1
    while len(out) < want:
        r = requests.get(f"{BASE}/companies", headers=headers,
                         params={"per_page": 50, "page": page}, timeout=30)
        r.raise_for_status()
        js = r.json()
        data = js.get("data", [])
        if not data:
            break
        out.extend(data)
        pag = js.get("meta", {}).get("pagination", {})
        if page >= pag.get("total_pages", page):
            break
        page += 1
    return out


def fetch_years(headers, edinet_code, years=5):
    r = requests.get(f"{BASE}/companies/{edinet_code}/financials",
                     headers=headers, params={"years": years}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def main():
    ap = argparse.ArgumentParser(description="業界ベンチマーク/トレンド参照データ生成")
    ap.add_argument("--sample", type=int, default=500, help="財務取得する社数の目安")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--out", default="data/reference")
    args = ap.parse_args()

    headers = _headers()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("企業インデックス（全社）を取得中...")
    idx = company_index(headers, 4000)        # 全社取得（デモ企業は散在するため）
    print(f"  インデックス {len(idx)} 社")
    by_edinet = {c["edinet_code"]: c for c in idx}
    # デモ企業の edinet_code を確実に含める
    demo_edinet = [c["edinet_code"] for c in idx if _norm_sec(c.get("sec_code")) in DEMO_SEC]
    targets = demo_edinet + [c["edinet_code"] for c in idx if c["edinet_code"] not in demo_edinet]
    targets = targets[:args.sample]
    print(f"対象 {len(targets)} 社（デモ企業 {len(demo_edinet)} 社含む）の財務を取得...")

    companies, by_industry = {}, {}
    for i, ec in enumerate(targets):
        try:
            rows = fetch_years(headers, ec, args.years)
        except requests.HTTPError:
            continue
        if not rows:
            continue
        meta = by_edinet.get(ec, {})
        sec = _norm_sec(meta.get("sec_code"))
        industry = meta.get("industry") or "その他"
        years_out = []
        for r in rows:
            ratios = compute_ratios(_row_schema(r))
            years_out.append({"fiscal_year": r.get("fiscal_year"),
                              "売上高": _row_schema(r)["売上高"],
                              "営業利益": _row_schema(r)["営業利益"],
                              "純資産": _row_schema(r)["純資産"],
                              "ratios": {k: ratios.get(k) for k in BENCH_RATIOS}})
        if sec:
            companies[sec] = {"name": meta.get("name"), "industry": industry, "years": years_out}
        # 業種中央値用に最新年度の指標を集計
        if years_out:
            latest = years_out[-1]["ratios"]
            by_industry.setdefault(industry, []).append(latest)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(targets)} ...")

    medians = {}
    for ind, rows in by_industry.items():
        med = {}
        for k in BENCH_RATIOS:
            vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
            if len(vals) >= 3:
                med[k] = round(statistics.median(vals), 2)
        medians[ind] = {"n": len(rows), "medians": med}

    (out / "companies.json").write_text(
        json.dumps(companies, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "sector_medians.json").write_text(
        json.dumps(medians, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完了: {len(companies)} 社, {len(medians)} 業種の中央値を {out} に保存。")
    print("デモ企業の格納:", [s for s in DEMO_SEC if s in companies])


if __name__ == "__main__":
    main()
