NeoBank AI — Demo Assets (Track 1, Hack the Liquid WAY)
========================================================

このフォルダを ZIP で暗号化し、パスワードを Discord で @liquid-yan に共有してください。
ZIP名: NeoBankAI_Track1_HackTheLiquidWAY_DemoAssets.zip

------------------------------------------------------------------
含めるファイル（撮影・作成して各行を置き換える）
------------------------------------------------------------------
[ ] demo_video.mp4 ........ 60〜90秒のデモ動画
                            （Wi-Fi OFF → 決算書投入 → 抽出+所見生成 →
                              「通信: ローカルのみ」表示まで）
[ ] screenshot_app.png .... アプリ全体画面
[ ] screenshot_json.png ... 抽出された財務JSON
[ ] screenshot_memo.png ... 生成された与信所見
[ ] product_photo.jpg ..... プロダクト/デモ環境の写真
[ ] team_photo.jpg ........ チーム（ソロ）写真
[ ] captions_bio.txt ...... キャプション＋自己紹介(bio)

------------------------------------------------------------------
プロダクト概要
------------------------------------------------------------------
NeoBank AI — 地方銀行向けのオンプレ融資稟議アシスタント。
決算書（画像/PDF）を端末内のLFMで読み取り、与信稟議の下書きを生成。
顧客の財務データは一切外部に出ない（データ主権）。

Why LFM: 顧客財務データはクラウドに出せない → クラウドLLMは「劣る」のではなく
そもそも使えない。オンデバイスLFMが唯一の現実解。

モデル : LFM2.5-VL-1.6B-Extract（抽出）＋ LFM2.5-1.2B-JP（所見, temp=0）
ランタイム: llama.cpp + Vulkan / FastFlowLM(NPU)
デバイス : AMD Ryzen AI PC

------------------------------------------------------------------
デモ起動手順（審査員が再現する場合）
------------------------------------------------------------------
1. cd neobank-ai && python3 -m venv .venv && source .venv/bin/activate
2. pip install -r requirements.txt
3. モデルサーバを 8080(VL)/8081(JP) で起動（会場: llama.cpp / 開発: python mock_server.py）
4. python app.py  →  http://localhost:7860  →「サンプルで試す」
   ※ 詳細は リポジトリの README.md を参照
