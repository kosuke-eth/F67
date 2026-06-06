"""EDINET DB（金融庁EDINETを構造化した第三者API）から実在企業の財務数値を取得し、
本アプリのスキーマ（百万円）に正規化して「正解データセット」を作る再実行可能CLI。

ベンチマークの正解ラベル＆将来のファインチューニング用ラベルを、手作業ゼロで量産する。
※ EDINET DB は PDF を返さないため、画像は別途レンダラ（make_statement.py）で生成する。

    python edinet_db.py --sample 20            # JP-GAAP企業を20社サンプルして gold を保存
    python edinet_db.py --codes E03006,E02144  # 指定企業

出力: data/gold/{edinet_code}_{fiscal_year}.json （アプリの8項目＋会社名・出典）
"""
import argparse
import json
import os
from pathlib import Path

import requests

from download_models import _load_env

BASE = "https://edinetdb.jp/v1"

# EDINET DB のフィールド → 本アプリのスキーマ（単位は円なので百万円へ /1e6）
# 有利子負債は ibd_current + ibd_noncurrent の合算で得る（XBRL単独タグが無い項目）。
FIELD_MAP = {
    "売上高": ("revenue",),
    "営業利益": ("operating_income",),
    "経常利益": ("ordinary_income",),       # IFRS/USGAAP では null のことがある
    "当期純利益": ("net_income",),
    "総資産": ("total_assets",),
    "純資産": ("net_assets",),
    "現預金": ("cash",),
    "有利子負債": ("ibd_current", "ibd_noncurrent"),  # 合算
}


def _headers() -> dict:
    _load_env(Path(__file__).with_name(".env"))
    key = os.environ.get("EDINETDB_API_KEY")
    if not key:
        raise SystemExit("EDINETDB_API_KEY が未設定です（.env を確認）")
    return {"X-API-Key": key}


def _yen_to_million(v):
    """円 → 百万円の整数。None はそのまま。"""
    if v is None:
        return None
    return int(round(v / 1_000_000))


def to_schema(row: dict) -> dict:
    """EDINET DB の1会計年度行 → アプリの8項目（百万円）。"""
    out = {"決算期": f"{row.get('fiscal_year')}年度"}
    for jp_key, src_keys in FIELD_MAP.items():
        vals = [row.get(k) for k in src_keys]
        if any(v is None for v in vals):
            out[jp_key] = None
        else:
            out[jp_key] = _yen_to_million(sum(vals))
    return out


def list_jp_companies(headers: dict, want: int) -> list:
    """JP-GAAP 企業の edinet_code を want 件集める（経常利益が取れる前提）。"""
    codes, cursor = [], None
    while len(codes) < want:
        params = {"limit": 100, "accounting_standard": "JP"}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE}/companies", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        for c in js.get("data", []):
            if c.get("accounting_standard") == "JP":
                codes.append((c["edinet_code"], c.get("name")))
        cursor = js.get("meta", {}).get("next_cursor")
        if not cursor:
            break
    return codes[:want]


def fetch_financials(headers: dict, code: str) -> list:
    r = requests.get(f"{BASE}/companies/{code}/financials",
                     headers=headers, params={"years": 1}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def main() -> None:
    ap = argparse.ArgumentParser(description="EDINET DB 正解データセット作成")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", type=int, help="JP-GAAP企業をN社サンプル")
    g.add_argument("--codes", help="カンマ区切りの edinet_code")
    ap.add_argument("--out", default="data/gold", help="保存先")
    args = ap.parse_args()

    headers = _headers()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.codes:
        targets = [(c.strip(), None) for c in args.codes.split(",")]
    else:
        print(f"JP-GAAP企業を {args.sample} 社サンプル中...")
        targets = list_jp_companies(headers, args.sample)

    saved = 0
    for code, name in targets:
        try:
            rows = fetch_financials(headers, code)
        except requests.HTTPError as e:
            print(f"  {code}: 取得失敗 {e}")
            continue
        if not rows:
            print(f"  {code}: データなし")
            continue
        row = rows[-1]  # 最新年度
        gold = to_schema(row)
        rec = {
            "edinet_code": code,
            "company": name or row.get("company_name"),
            "fiscal_year": row.get("fiscal_year"),
            "edinet_filing_url": row.get("edinet_filing_url"),
            "doc_id": row.get("doc_id"),
            "credit_rating": row.get("credit_rating"),  # EDINET DB の参考格付け
            "gold": gold,
        }
        missing = [k for k, v in gold.items() if v is None and k != "決算期"]
        path = out / f"{code}_{row.get('fiscal_year')}.json"
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        flag = f"  ⚠欠損: {missing}" if missing else ""
        print(f"  ✓ {code} {rec['company']}  FY{rec['fiscal_year']}  "
              f"売上{gold['売上高']}百万円{flag}")
        saved += 1

    print(f"\n完了: {saved} 件の正解データを {out} に保存。次は make_statement.py で画像化してベンチ。")


if __name__ == "__main__":
    main()
