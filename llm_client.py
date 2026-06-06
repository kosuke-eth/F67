"""ローカルのOpenAI互換エンドポイント（llama.cpp server / LEAP / FastFlowLM /
開発用 mock_server）を叩く薄いクライアント。外部ネットワークには出ない。"""
import base64
import os
import time

import requests

VL_BASE_URL = os.environ.get("VL_BASE_URL", "http://127.0.0.1:8080/v1")
VL_MODEL = os.environ.get("VL_MODEL", "LFM2.5-VL-1.6B")
JP_BASE_URL = os.environ.get("JP_BASE_URL", "http://127.0.0.1:8081/v1")
JP_MODEL = os.environ.get("JP_MODEL", "LFM2.5-1.2B-JP-202606")


def is_local_only() -> bool:
    """全エンドポイントが localhost なら True（デモで「外部送信なし」を示す用）。"""
    return all(("localhost" in u) or ("127.0.0.1" in u)
               for u in (VL_BASE_URL, JP_BASE_URL))


def _chat(base_url, model, messages, temperature=0.0, max_tokens=1024):
    t0 = time.perf_counter()
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={"model": model, "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=120,
    )
    resp.raise_for_status()
    latency = time.perf_counter() - t0
    return resp.json()["choices"][0]["message"]["content"], latency


def vl_extract(image_bytes, prompt):
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]}]
    return _chat(VL_BASE_URL, VL_MODEL, messages, temperature=0.0)


def jp_generate(system, user):
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    return _chat(JP_BASE_URL, JP_MODEL, messages, temperature=0.0)
