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


def op():
    """関数デコレータ。weave があればトレース、無ければ素通し。"""
    def deco(fn):
        if _HAS_WEAVE:
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
