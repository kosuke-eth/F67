# 📋 提出パッケージ — NeoBank AI（Track 1）

Hack the Liquid WAY の Submission Guide に沿った提出物一式。`[ ]` を埋めながら使う。

> チーム名は仮に **NeoBankAI** とする。実際の登録名に置き換えること（特にデモ素材フォルダ名）。

---

## 0. トラック選択

- **Track 1: LFM Application Track**（ソロ可。on-device は加点、必須ではない）

---

## 1. タグライン（1〜2行）

提出フォーム用。いずれか1つ：

- **"Underwriting that never leaves the bank."**（データ主権を前面に）
- **"On-device credit AI for Japan's 100 regional banks."**（市場を前面に）
- **"The credit-memo copilot banks can actually use — because nothing leaves the building."**

---

## 2. スライドデッキ（2〜4枚）✅

- ファイル: `NeoBank_AI_Deck.pptx`（英語。登壇は日本語の想定）
- 内容: ①課題（地銀の与信） ②Why LFM（クラウドは"使えない"） ③構成＋オンデバイス性能 ④市場と初顧客
- これがそのままライブデモの台本になる。

---

## 3. ライブデモ（5分）台本

1. **痛み（30秒）**: 「地銀の融資審査は属人的で時間がかかる。約100行が同じ問題を抱える」
2. **なぜ今まで無理（30秒）**: 「顧客の財務データを外部クラウドに出せず、生成AIを使えなかった」← Why LFMの核
3. **デモ（2分半）**: **その場でWi-Fiを切る** → `python app.py` → 決算書を投入 → 数秒で抽出＋与信所見。`🔒 通信: ローカルのみ` を見せる
4. **数字（30秒）**: 抽出レイテンシ◯秒 / メモリ◯GB / クラウドAPI比コスト◯%減（Ryzen実測値）
5. **初顧客（1分）**: 「1行で実証 → 地銀ネットワークへ横展開」= WAYのロールアップ論

---

## 4. 公開リポジトリ

オープンソース提出規約に基づく公開GitHubリポジトリのリンクを提出。

```bash
cd neobank-ai
git init
git add .
git commit -m "NeoBank AI — on-device loan-memo assistant (Track 1)"
# GitHubで空リポジトリ neobank-ai を作成してから:
git remote add origin https://github.com/<your-account>/neobank-ai.git
git branch -M main
git push -u origin main
```

- `.gitignore` で `.venv` / `.env` / `__pycache__` は除外済み（鍵やローカル環境は上げない）。
- ライセンスは `LICENSE`（MIT）。

---

## 5. デモ素材フォルダ（暗号化して提出）

- フォルダ名: **`NeoBankAI_Track1_HackTheLiquidWAY_DemoAssets`**（同梱の雛形を使用）
- ZIPを暗号化し、**パスワードはDiscordで @liquid-yan にDM**。
- 中身（`demo_assets/.../README.txt` に詳細）:
  - [ ] 60〜90秒のデモ動画（Wi-Fi OFF → 投入 → 所見生成 → ローカル通信表示）
  - [ ] 高解像度スクリーンショット（アプリ画面、抽出JSON、所見）
  - [ ] プロダクト写真／チーム写真
  - [ ] キャプション・自己紹介（bio）
  - [ ] `README.txt`（ファイル説明＋デモ起動手順）

暗号化の例:
```bash
cd demo_assets
zip -er NeoBankAI_Track1_HackTheLiquidWAY_DemoAssets.zip NeoBankAI_Track1_HackTheLiquidWAY_DemoAssets
# パスワードを設定 → @liquid-yan に共有
```

---

## 6. テクニカルサマリー

| 項目 | 内容 |
|---|---|
| モデル | `LFM2.5-VL-1.6B-Extract`（抽出）＋ `LFM2.5-1.2B-JP`（与信所見, temperature=0） |
| フレームワーク | Python / Gradio。OpenAI互換APIで各モデルサーバへ |
| ランタイム | llama.cpp + Vulkan（VL）／FastFlowLM・`.q4nx` NPU（JPテキスト, 任意） |
| デバイス | AMD Ryzen AI PC（XDNA 2 NPU / Radeon iGPU） |
| レイテンシ | 抽出 ◯s / 所見 ◯s / 合計 ◯s（`eval_weave.py` で実測） |
| メモリ | 約◯GB（会場で実測） |
| 通信 | 外部送信ゼロ（全処理オンデバイス） |
| 評価 | `eval_weave.py`：抽出フィールド一致率＋レイテンシ。W&B Weaveで記録可 |

**キーとなる技術的工夫**:
1. **抽出専用VL（-Extract）＋ 決定的な指標エンジン（Python）** の分担で、小型モデルでも与信に足る精度と再現性を確保。
2. **temperature=0 ＋ Python算出** により「同じ書類なら同じ所見」= 監査で再現可能（クラウドSLAでは担保しづらい領域）。
3. アーキテクチャ図は **デッキ Slide 3**（フロー図）を参照。

**W&B Weave（加点）**: `extract_financials` / `risk_summary` を `@op()` でトレース。`eval_weave.py` で
抽出精度・レイテンシを評価として記録。`ENABLE_WEAVE=1 WANDB_API_KEY=... python eval_weave.py` で有効化。学習は不要。

---

## 7. 提出前チェックリスト

- [ ] トラック確定（Track 1）
- [ ] デッキ最終化（`*Indicative` をRyzen実測値に差し替え）
- [ ] タグライン決定
- [ ] 公開リポジトリ push 済み・リンク取得
- [ ] デモ動画（60〜90秒）撮影
- [ ] デモ素材フォルダを規定名で暗号化 → @liquid-yan にパスワード共有
- [ ] テクニカルサマリーの数値を実測値で更新
- [ ] Discord参加済み（Day2提出に必要）
