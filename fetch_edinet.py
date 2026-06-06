"""EDINET（金融庁の公式開示システム）から実在の決算書類を取得する再実行可能CLI。

ベンチマーク用に「実物の有価証券報告書 PDF」と「その XBRL/CSV（＝正解値の素）」を落とす。
XBRL/CSV には各財務数値が構造化データで入っているため、手作業ラベル無しで正解が得られる。

    python fetch_edinet.py --date 2025-06-27 --doc-type 120 --limit 5
    python fetch_edinet.py --list-only --date 2025-06-27   # まず何があるか一覧だけ見る

APIキー（Subscription-Key）は EDINET でアカウント開設すると無料で発行される（.env の EDINET_API_KEY）。
取得: https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1 （MFA後、連絡先登録でキー表示）
"""
import argparse
import os
import zipfile
from pathlib import Path

import requests

from download_models import _load_env  # 小さな .env ローダを再利用

BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"

# docTypeCode（提出書類種別）の主なもの
DOC_TYPES = {
    "120": "有価証券報告書",
    "140": "四半期報告書",
    "160": "半期報告書",
    "350": "決算短信",  # 参考（EDINETでの扱いは限定的）
}

# 取得種別（documents/{docID}?type=N）
TYPE_PDF = 2   # 提出書類本文 PDF
TYPE_CSV = 5   # XBRL を CSV 化したもの（正解値の抽出が容易）


def _key() -> str:
    _load_env(Path(__file__).with_name(".env"))
    k = os.environ.get("EDINET_API_KEY")
    if not k:
        raise SystemExit(
            "EDINET_API_KEY が未設定です。\n"
            "  1) https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1 でアカウント開設\n"
            "  2) 発行された Subscription-Key を .env の EDINET_API_KEY= に貼る")
    return k


def list_documents(date: str, key: str) -> list:
    """指定日に提出された書類の一覧（メタデータ）を返す。"""
    r = requests.get(f"{BASE}/documents.json",
                     params={"date": date, "type": 2, "Subscription-Key": key},
                     timeout=30)
    r.raise_for_status()
    js = r.json()
    status = js.get("metadata", {}).get("status")
    if status not in (None, "200"):
        raise SystemExit(f"EDINET エラー: {js.get('metadata', {}).get('message')}")
    return js.get("results", []) or []


def download(doc_id: str, dtype: int, out: Path, key: str) -> Path | None:
    """書類を取得。type=PDF はそのまま、type=CSV は ZIP を展開して保存。"""
    r = requests.get(f"{BASE}/documents/{doc_id}",
                     params={"type": dtype, "Subscription-Key": key}, timeout=60)
    if r.status_code != 200 or r.headers.get("Content-Type", "").startswith("application/json"):
        print(f"    （type={dtype} は取得不可: {r.status_code}）")
        return None
    if dtype == TYPE_PDF:
        p = out / f"{doc_id}.pdf"
        p.write_bytes(r.content)
        return p
    # CSV は ZIP。展開して csv をまとめて置く
    zpath = out / f"{doc_id}_csv.zip"
    zpath.write_bytes(r.content)
    cdir = out / f"{doc_id}_csv"
    cdir.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(cdir)
    except zipfile.BadZipFile:
        print("    （CSV ZIP の展開に失敗）")
        return None
    return cdir


def main() -> None:
    ap = argparse.ArgumentParser(description="EDINET 実データ取得")
    ap.add_argument("--date", required=True, help="提出日 YYYY-MM-DD")
    ap.add_argument("--doc-type", default="120",
                    help=f"docTypeCode（既定120=有報）。種別: {DOC_TYPES}")
    ap.add_argument("--limit", type=int, default=5, help="取得件数の上限")
    ap.add_argument("--out", default="data/edinet", help="保存先")
    ap.add_argument("--list-only", action="store_true", help="一覧表示のみ（DLしない）")
    args = ap.parse_args()

    key = _key()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    docs = list_documents(args.date, key)
    hits = [d for d in docs if d.get("docTypeCode") == args.doc_type
            and d.get("pdfFlag") == "1"]
    print(f"{args.date}: 全{len(docs)}件中、種別{args.doc_type}"
          f"（{DOC_TYPES.get(args.doc_type, '?')}）でPDFありは {len(hits)} 件")

    if args.list_only:
        for d in hits[:args.limit]:
            print(f"  {d['docID']}  {d.get('filerName')}  "
                  f"secCode={d.get('secCode')}  csvFlag={d.get('csvFlag')}")
        return

    saved = 0
    for d in hits:
        if saved >= args.limit:
            break
        doc_id = d["docID"]
        print(f"[{saved + 1}/{args.limit}] {doc_id}  {d.get('filerName')}")
        pdf = download(doc_id, TYPE_PDF, out, key)
        csv = download(doc_id, TYPE_CSV, out, key) if d.get("csvFlag") == "1" else None
        if pdf:
            print(f"    PDF → {pdf}")
        if csv:
            print(f"    CSV → {csv}")
        if pdf:
            saved += 1
    print(f"\n完了: {saved} 件を {out} に保存。次は CSV から正解値を抽出して eval に投入する。")


if __name__ == "__main__":
    main()
