"""定性分析: 決算書類の本文テキスト → 与信に関わる定性情報の要約（Liquid・端末内）。

数値は VL が読むが、事業概況・リスク要因・見通しといった「文章」は本文から読む方が正確。
EDINET/IR の PDF はデジタル（スキャンではない）ため pypdfium2 で全頁のテキストを高速抽出できる。
要約は LFM2.5-JP が担当し、本文に無い事項は推測しない（監査可能性のため）。
"""
import pypdfium2 as pdfium

from tracing import op
from llm_client import jp_generate

QUAL_SYSTEM = (
    "あなたは地方銀行の与信審査を補助するアシスタントです。"
    "決算書類の本文テキストから、与信判断に関わる定性情報のみを事実に忠実に抽出・要約します。"
    "本文に無い事項は推測せず省略します。日本語で簡潔に、各項目2〜4行程度。"
)
_QUAL_HEAD = (
    "次の決算書類テキストから、以下の観点で定性情報を箇条書きで要約してください。\n"
    "■ 事業の概況（主力事業・当期業績の背景）\n"
    "■ リスク要因（本文で言及された事業・財務上のリスク）\n"
    "■ 今後の見通し（業績予想・経営方針）\n"
    "■ その他特記事項（あれば）\n"
    "本文に該当する記述が無い項目は「記載なし」と書くこと。\n\n"
    "【決算書類テキスト】\n"
)


def document_text(file_path: str, max_pages: int = 6) -> str:
    """PDF（デジタル前提）の本文テキストを先頭 max_pages 頁ぶん抽出。画像入力は空。"""
    if not file_path or not file_path.lower().endswith(".pdf"):
        return ""
    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception:
        return ""
    parts = []
    for i in range(min(len(pdf), max_pages)):
        try:
            parts.append(pdf[i].get_textpage().get_text_range())
        except Exception:
            continue
    return "\n".join(parts).strip()


@op()
def qualitative_summary(doc_text: str):
    """本文テキスト → 定性要約（事業概況・リスク・見通し）。空なら ("", 0.0)。"""
    text = (doc_text or "").strip()
    if len(text) < 40:                       # テキストがほぼ無い（画像入力など）
        return "", 0.0
    return jp_generate(QUAL_SYSTEM, _QUAL_HEAD + text[:6000])
