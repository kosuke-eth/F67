# 🏦 NeoBank AI — オンプレ融資稟議アシスタント

地方銀行の融資審査を、**顧客データを一切外部に出さずに**支援するオンデバイスAIツール。
決算書（画像 / PDF）を入れると、端末内のLFMで財務数値を抽出し、与信稟議書の下書きを生成する。

**Why LFM（クラウドではない理由）**: 顧客の財務情報は外部クラウドに送信できない（データ主権・規制）。
クラウドLLMは「精度が劣る」のではなく **そもそも使えない**。オンデバイスLFMが唯一の現実解。

---

## アーキテクチャ

```
決算書（画像/PDF）
   │
   ▼
[LFM2.5-VL-1.6B]  日本語ビジョン対応VL。抽出専用プロンプトで拘束
   │  構造化JSON（売上・利益・総資産…）
   ▼
[Python: 整合性チェック]  純資産>総資産 等の抽出ミスを検知（監査の土台）
   │
   ▼
[Python: 指標を決定的に算出]  自己資本比率・営業利益率・経常利益率・ROE・ROA・DEレシオ・ネット負債
   │  ＋ 暫定格付け(A〜D) を3指標から決定的にスコア化
   ▼
[LFM2.5-1.2B-JP-202606]  temperature=0  与信所見を日本語生成（決定性=監査で再現可能）
   │
   ▼
与信稟議の下書き  +  オンデバイス性能（レイテンシ / 通信ローカル表示）
```

すべて AMD Ryzen AI PC 上でローカル実行。外部ネットワーク通信ゼロ。

---

## クイックスタート

```bash
pip install -r requirements.txt
cp .env.example .env
```

### A) 開発モード（モデル不要・今すぐ動く）

本物のLFMが無くても、同梱のモックLFMで全パイプラインが動く。UXを先に完成させる用＋本番の保険。

```bash
# 別ターミナルで2つ起動（VL=8080, JP=8081）
python mock_server.py --port 8080
python mock_server.py --port 8081

# アプリ起動 → http://localhost:7860
python app.py
```

UIなしで素早く確認するなら:

```bash
python run_demo.py          # サンプル決算書で抽出→指標→所見を一気に実行
```

### B) 会場モード（Ryzen AI PC + 本物のLFM）

`llama.cpp + Vulkan`（プリインストール）でVLとJPを別ポートに立て、`.env` を向けるだけ。

```bash
llama-server -m models/LFM2.5-VL-1.6B.gguf            --port 8080 --host 127.0.0.1 --mmproj models/LFM2.5-VL-1.6B-mmproj.gguf
llama-server -m models/LFM2.5-1.2B-JP-202606.gguf     --port 8081 --host 127.0.0.1
python app.py
```

> テキストパスをNPUで高速化するなら FastFlowLM（`.q4nx`）に差し替え、`JP_BASE_URL` を
> そのOpenAI互換エンドポイントへ。会場メンター（Teo / Kohsei）にランタイム選択を相談すること。
> `localhost` がIPv6に解決される環境があるため、デフォルトは `127.0.0.1` にしてある。

---

## 動作確認済み

- `pytest -q` → 9 件パス（指標計算・整合性チェック・格付け・JSON正規化のロジック）
- `python run_demo.py`（モックLFM）→ 抽出→整合性→指標→格付け→所見まで一気通貫で出力を確認
  - 例: 自己資本比率 27.5% / 営業利益率 6.1% / ROE 11.3% / DEレシオ 1.46倍 → 暫定格付け **B (3/6)** を決定的に算出
- 抽出が壊れたJSONを返しても、修復プロンプトで1回自動リトライ（実機VLの揺れに耐性）
- 画像・PDF どちらの入力も PNG 変換を確認

---

## W&B Weave（加点要素）

`extract_financials` と `risk_summary` は `@op()`（`tracing.py`）でラップ済み。
weave があれば入出力とレイテンシをトレース、無ければ素通しで動く。
`WEAVE_PROJECT` を設定し `weave` をインストールすれば自動で有効化。学習は不要。

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `app.py` | Gradio UI（エンドユーザー＝銀行員向け。画像/PDF対応） |
| `extract.py` | 決算書 → 構造化JSON（VL-Extract）＋頑健なパース |
| `summarize.py` | 財務数値 → 与信所見（JP, 決定的）＋指標エンジン |
| `llm_client.py` | ローカルOpenAI互換エンドポイントの薄いクライアント |
| `mock_server.py` | 開発用モックLFM（OpenAI互換）。モデル不要で全体を駆動 |
| `make_sample.py` | デモ用サンプル決算書画像を生成 |
| `run_demo.py` | UIなしで全パイプラインを実行（録画/確認用） |
| `sample_data.py` | サンプル財務データ（架空企業） |
| `tracing.py` | Weave トレース（フォールバック付き） |
| `tests/` | ロジックの単体テスト |

---

## デモ台本（5分）

1. **痛み**: 「地銀の融資審査は属人的で時間がかかる。約100行が同じ問題を抱える」
2. **なぜ今まで無理**: 「顧客の財務データを外部クラウドに出せず、生成AIを使えなかった」
3. **その場でWi-Fiを切る** → 決算書を投入 → 数秒で抽出＋所見。`🔒 通信: ローカルのみ` を見せる
4. **数字**: レイテンシ◯秒 / メモリ◯GB / クラウドAPI比コスト◯%減
5. **1st customer**: 「1行で実証 → 地銀ネットワークへ横展開」（= WAYのロールアップ論）

## データ取扱い
デモは公開IR想定の架空サンプルのみ使用。実顧客データは使用しない。

---

## 提出（Hack the Liquid WAY）

提出物一式と手順は **`SUBMISSION.md`** にまとめてある（トラック / タグライン / デモ台本 /
公開リポジトリ手順 / 暗号化デモ素材フォルダ / テクニカルサマリー / チェックリスト）。

- 評価: `python eval_weave.py`（抽出精度＋レイテンシ。`ENABLE_WEAVE=1 WANDB_API_KEY=...` でW&B記録）
- デモ素材雛形: `demo_assets/NeoBankAI_Track1_HackTheLiquidWAY_DemoAssets/`
