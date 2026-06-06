"""LFM の GGUF をローカルに取得する再実行可能なCLI（このPCでも会場のRyzen機でも同一手順）。

    python download_models.py                 # 既定: VL=Q8_0(+mmproj Q8_0), JP=Q6_K を models/ へ
    python download_models.py --vl-quant Q4_0 # 軽量版（速度優先・精度はやや低下）
    python download_models.py --skip-vl       # JPだけ取得

トークンは環境変数 HF_TOKEN（または .env）から読む。引数や出力には一切表示しない。
取得後の起動例は print で案内する。会場はオフライン想定なので事前にここで落としておく。
"""
import argparse
import os
from pathlib import Path

from huggingface_hub import hf_hub_download

VL_REPO = "LiquidAI/LFM2.5-VL-1.6B-GGUF"
JP_REPO = "LiquidAI/LFM2.5-1.2B-JP-202606-GGUF"

# mmproj は Q8_0 までしか無い & 視覚射影は高精度が無難なので quant に依らず Q8_0 を使う
MMPROJ_FILE = "mmproj-LFM2.5-VL-1.6b-Q8_0.gguf"


def _load_env(env_path: Path) -> None:
    """.env があれば HF_TOKEN 等を環境に流し込む（python-dotenv 非依存の最小実装）。"""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _get(repo: str, filename: str, out: Path, token: str) -> Path:
    print(f"  ↓ {repo} :: {filename}")
    p = hf_hub_download(repo_id=repo, filename=filename, local_dir=str(out), token=token)
    print(f"    → {p}")
    return Path(p)


def main() -> None:
    ap = argparse.ArgumentParser(description="LFM GGUF ダウンローダ")
    ap.add_argument("--out", default="models", help="保存先ディレクトリ（既定: models）")
    ap.add_argument("--vl-quant", default="Q8_0",
                    choices=["Q4_0", "Q8_0", "F16", "BF16"], help="VL 本体の量子化")
    ap.add_argument("--jp-quant", default="Q6_K",
                    choices=["Q4_0", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "F16"],
                    help="JP テキストの量子化")
    ap.add_argument("--skip-vl", action="store_true", help="VL を取得しない")
    ap.add_argument("--skip-jp", action="store_true", help="JP を取得しない")
    args = ap.parse_args()

    _load_env(Path(__file__).with_name(".env"))
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN が未設定です（.env に書くか環境変数で渡してください）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LFM GGUF ダウンロード")
    print("=" * 60)

    vl_model = vl_mmproj = jp_model = None
    if not args.skip_vl:
        print("[VL] LFM2.5-VL-1.6B")
        vl_model = _get(VL_REPO, f"LFM2.5-VL-1.6B-{args.vl_quant}.gguf", out, token)
        vl_mmproj = _get(VL_REPO, MMPROJ_FILE, out, token)
    if not args.skip_jp:
        print("[JP] LFM2.5-1.2B-JP-202606")
        jp_model = _get(JP_REPO, f"LFM2.5-1.2B-JP-202606-{args.jp_quant}.gguf", out, token)

    print("\n完了。llama.cpp 起動例（別ターミナルで2つ）:")
    if vl_model:
        print(f"  llama-server -m {vl_model} --mmproj {vl_mmproj} "
              f"--port 8080 --host 127.0.0.1")
    if jp_model:
        print(f"  llama-server -m {jp_model} --port 8081 --host 127.0.0.1")
    print("  その後  python app.py  /  python run_demo.py  /  python eval_weave.py")


if __name__ == "__main__":
    main()
