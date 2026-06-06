"""簡易評価ハーネス（Track 1 の W&B Weave 加点用）。
サンプル決算書に対する「抽出精度（フィールド一致率）」と「レイテンシ」を測る。

事前に mock_server（開発）か本物のLFM（会場）を 8080/8081 で起動しておくこと。
W&Bに記録するには:  ENABLE_WEAVE=1 WANDB_API_KEY=xxxx python eval_weave.py
（フラグ未設定なら記録なしでローカル計測のみ）

本番は CASES を実決算書（公開IR）＋手で作った正解で複数件に増やすほど評価が厳密になる。
"""
import tracing
from extract import extract_financials
from summarize import risk_summary
from make_sample import make_sample
from sample_data import SAMPLE_FINANCIALS

tracing.init("neobank-ai-eval")

# (画像パス, 正解辞書) のデータセット
CASES = [(make_sample("eval_sample.png"), SAMPLE_FINANCIALS)]

NUMERIC = [k for k in SAMPLE_FINANCIALS if k != "決算期"]


def field_accuracy(pred: dict, gold: dict) -> float:
    hit = sum(1 for k in NUMERIC if pred.get(k) == gold.get(k))
    return hit / len(NUMERIC)


def main():
    accs, ext_lat, sum_lat = [], [], []
    print("=" * 56)
    print("NeoBank AI — 抽出精度 / レイテンシ評価")
    print("=" * 56)
    for path, gold in CASES:
        with open(path, "rb") as f:
            img = f.read()
        pred, t1 = extract_financials(img)
        _, t2, _ = risk_summary(pred)
        acc = field_accuracy(pred, gold)
        accs.append(acc); ext_lat.append(t1); sum_lat.append(t2)
        print(f"  {path}: 抽出精度 {acc * 100:.0f}%  /  抽出 {t1:.2f}s  /  所見 {t2:.2f}s")

    n = len(CASES)
    print("-" * 56)
    print(f"件数              : {n}")
    print(f"平均 抽出精度     : {sum(accs) / n * 100:.1f}%")
    print(f"平均 抽出レイテンシ: {sum(ext_lat) / n:.2f}s")
    print(f"平均 所見レイテンシ: {sum(sum_lat) / n:.2f}s")
    print(f"平均 合計レイテンシ: {(sum(ext_lat) + sum(sum_lat)) / n:.2f}s")


if __name__ == "__main__":
    main()
