import json
from make_statement import render_statement
from llm_client import vl_extract
from extract import EXTRACT_PROMPT

rec = json.loads(open("data/gold/E00508_2025.json", encoding="utf-8").read())
gold = rec["gold"]
print("会社:", rec["company"], "FY", rec["fiscal_year"])
print("GOLD:", {k: v for k, v in gold.items() if k != "決算期"})
for t in range(3):
    img = f"data/rendered/_dbg_t{t}.png"
    render_statement(gold, rec["company"], gold.get("決算期"), img, template=t, seed=t)
    raw, lat = vl_extract(open(img, "rb").read(), EXTRACT_PROMPT)
    print(f"\n--- template {t}  ({lat:.2f}s) ---")
    print("RAW:", raw[:400].replace(chr(10), " "))
