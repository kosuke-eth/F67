"""抽出ベンチマーク（実在企業の財務データ＝EDINET DB を正解に使う）。

各社の gold（data/gold/*.json）を決算書画像にレンダリングし、VLで抽出 → 正解と突合。
測るもの:
  - フィールド一致率（全体／項目別）   ← 抽出の素の精度
  - 完全一致率（全項目正解の社数）
  - 整合性アラート発火率              ← 決定的レイヤ（堀）の効き
  - レイテンシ（抽出／所見）

事前に VL/JP サーバ（8080/8081）を起動しておくこと。
W&Bに記録: ENABLE_WEAVE=1 WANDB_API_KEY=... python eval_weave.py
正解データ作成: python edinet_db.py --sample 24
"""
import glob
import json
import os
from collections import defaultdict

import tracing
from extract import extract_financials
from summarize import compute_ratios, validate_financials
from make_statement import render_statement
from make_sample import make_sample
from sample_data import SAMPLE_FINANCIALS

tracing.init(os.environ.get("WEAVE_PROJECT", "neobank-ai") + "-eval")

GOLD_DIR = "data/gold"
RENDER_DIR = "data/rendered"
NUMERIC = [k for k in SAMPLE_FINANCIALS if k != "決算期"]


def load_cases():
    """gold JSON を読み込み (画像パス, gold, 会社名) のリストにする。
    gold が無ければ同梱の合成サンプル1件にフォールバック。"""
    os.makedirs(RENDER_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(GOLD_DIR, "*.json")))
    if not files:
        print("[eval] gold が無いので合成サンプルで実行（python edinet_db.py --sample N で実データ化）")
        return [(make_sample("eval_sample.png"), SAMPLE_FINANCIALS, "サンプル")]

    cases = []
    for i, fp in enumerate(files):
        rec = json.loads(open(fp, encoding="utf-8").read())
        gold = rec["gold"]
        img = os.path.join(RENDER_DIR, f"{rec['edinet_code']}_{rec['fiscal_year']}.png")
        # テンプレートを巡回させ、レイアウト頑健性も同時に評価
        # EVAL_TEMPLATE=1 等で単一テンプレートに固定すると変数を切り分けられる
        forced = os.environ.get("EVAL_TEMPLATE")
        tmpl = int(forced) if forced is not None else i % 3
        render_statement(gold, rec.get("company"), gold.get("決算期"),
                         img, template=tmpl, seed=i)
        cases.append((img, gold, rec.get("company")))
    return cases


def graded_fields(gold: dict):
    """正解が非nullの項目だけを採点対象にする。"""
    return [k for k in NUMERIC if gold.get(k) is not None]


def main():
    cases = load_cases()
    n = len(cases)
    per_field_hit = defaultdict(int)
    per_field_tot = defaultdict(int)
    exact, flagged_total, flagged_on_error = 0, 0, 0
    ext_lat, sum_lat_proxy = [], []
    total_hit, total_fields = 0, 0

    print("=" * 64)
    print(f"NeoBank AI — 抽出ベンチマーク（実データ {n} 社）")
    print("=" * 64)

    for img, gold, name in cases:
        with open(img, "rb") as f:
            pred, t1 = extract_financials(f.read())
        ext_lat.append(t1)

        gf = graded_fields(gold)
        hits = sum(1 for k in gf if pred.get(k) == gold.get(k))
        for k in gf:
            per_field_tot[k] += 1
            if pred.get(k) == gold.get(k):
                per_field_hit[k] += 1
        total_hit += hits; total_fields += len(gf)
        case_acc = hits / len(gf) if gf else 0.0
        if hits == len(gf):
            exact += 1

        # 堀の効き: 抽出に誤りがある社で、整合性アラートが鳴ったか
        warnings = validate_financials(pred)
        had_error = hits < len(gf)
        if warnings:
            flagged_total += 1
            if had_error:
                flagged_on_error += 1

        mark = "✓" if not had_error else ("⚑" if warnings else "✗")
        disp = (name or "")[:18]
        print(f"  {mark} {disp:<18} 一致 {hits}/{len(gf)} ({case_acc*100:3.0f}%)"
              f"  抽出 {t1:4.1f}s" + ("  [アラート]" if warnings else ""))

    print("-" * 64)
    overall = total_hit / total_fields * 100 if total_fields else 0
    print(f"社数                : {n}")
    print(f"フィールド一致率     : {overall:.1f}%  ({total_hit}/{total_fields})")
    print(f"完全一致（全項目正解）: {exact}/{n}  ({exact/n*100:.0f}%)")
    print(f"平均 抽出レイテンシ   : {sum(ext_lat)/n:.2f}s")
    print(f"整合性アラート発火    : {flagged_total} 社"
          f"（うち実際に誤りを含む: {flagged_on_error}）")
    print("\n項目別 一致率:")
    for k in NUMERIC:
        if per_field_tot[k]:
            acc = per_field_hit[k] / per_field_tot[k] * 100
            print(f"  {k:<8}: {acc:5.1f}%  ({per_field_hit[k]}/{per_field_tot[k]})")

    _log_wandb(overall, exact / n * 100, sum(ext_lat) / n,
               flagged_total, flagged_on_error, per_field_hit, per_field_tot)


def _log_wandb(overall, exact_pct, lat, flagged, flagged_err, pf_hit, pf_tot):
    """集計値を W&B に残す（任意・加点）。失敗しても本体は止めない。"""
    if not (os.environ.get("WANDB_API_KEY") or os.environ.get("ENABLE_WEAVE")):
        return
    try:
        import wandb
        run = wandb.init(entity=os.environ.get("WANDB_ENTITY"),
                         project=os.environ.get("WEAVE_PROJECT", "neobank-ai") + "-eval",
                         job_type="extract-benchmark", reinit=True)
        metrics = {"field_accuracy_pct": overall, "exact_match_pct": exact_pct,
                   "mean_extract_latency_s": lat,
                   "consistency_alerts": flagged, "alerts_on_error": flagged_err}
        for k in pf_tot:
            metrics[f"field_acc/{k}"] = pf_hit[k] / pf_tot[k] * 100
        run.log(metrics)
        run.finish()
        print("\n[wandb] 集計を記録しました。")
    except Exception as e:
        print(f"\n[wandb] 記録スキップ: {e}")


if __name__ == "__main__":
    main()
