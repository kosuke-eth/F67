"""W&B Weave のトレースを使う。weave が無い／オフラインでも動くよう
@op() はフォールバックで素通しになる。
init() は WANDB_API_KEY か ENABLE_WEAVE がある時だけ起動する
（weave.init の対話的ログインプロンプトで起動が止まるのを防ぐ）。"""
import os

try:
    import weave  # noqa
    _HAS_WEAVE = True
except Exception:
    _HAS_WEAVE = False


def _weave_enabled() -> bool:
    """明示的にONのときだけ weave を使う（init と同じゲート）。
    未設定だとライブデモ中に「Traces will not be logged」の赤い警告が出るため、
    フラグ無しでは weave.op() を一切適用しない。"""
    return _HAS_WEAVE and bool(
        os.environ.get("WANDB_API_KEY") or os.environ.get("ENABLE_WEAVE"))


def op():
    """関数デコレータ。weave が有効ならトレース、無ければ素通し。"""
    def deco(fn):
        if _weave_enabled():
            return weave.op()(fn)
        return fn
    return deco


def init(project: str) -> bool:
    if not _HAS_WEAVE:
        return False
    # 明示的にONのときだけ起動（未設定ならW&Bログインで止まらない）
    if not (os.environ.get("WANDB_API_KEY") or os.environ.get("ENABLE_WEAVE")):
        return False
    try:
        weave.init(project)
        return True
    except Exception as e:
        print(f"[weave] 初期化スキップ: {e}")
        return False
