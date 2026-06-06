"""UIなしで全パイプラインを通すドライバ（動作確認・デモ録画用）。
事前に mock_server を 8080/8081 で起動しておくこと（または .env を本物に向ける）。

    python run_demo.py [画像パス]
"""
import sys

from extract import extract_financials
from summarize import risk_summary
from llm_client import is_local_only
from make_sample import make_sample


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else make_sample()
    with open(path, "rb") as f:
        img = f.read()

    print("=" * 64)
    print("NeoBank AI — フルパイプライン実行")
    print("通信:", "ローカルのみ（外部送信なし）" if is_local_only() else "外部エンドポイント")
    print("=" * 64)

    data, t1 = extract_financials(img)
    print(f"\n[1] 抽出（{t1:.3f}s）")
    for k, v in data.items():
        print(f"    {k}: {v}")

    memo, t2, ratios, grade, warnings = risk_summary(data)
    print(f"\n[2] 算出指標")
    for k, v in ratios.items():
        print(f"    {k}: {v}")
    print(f"\n[3] 暫定格付け: {grade.get('格付け')}（{grade.get('スコア')}）")
    for r in grade.get("根拠", []):
        print(f"    - {r}")
    if warnings:
        print("\n[!] 整合性アラート")
        for w in warnings:
            print(f"    - {w}")
    print(f"\n[4] 与信所見（{t2:.3f}s）\n")
    print(memo)
    print("\n" + "=" * 64)
    print(f"合計レイテンシ: {t1 + t2:.3f}s")


if __name__ == "__main__":
    main()
