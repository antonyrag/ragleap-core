# Generates lower() and code-point ordering fixtures from Python's own str behaviour (Python 3.10, Unicode 13).
import json, os
LOWER = ["ABC", "\u03a3", "\u0391\u03a3", "\u0391\u03a3 \u0391\u03a3", "\u0391\u03a3\u0391", "\u0130", "\u0130stanbul",
         "\u1e9e", "\u01c5", "\u01c4", "\u03a3\u0391\u03a3.", "\u03a3.", "\u0391\u03a3'", "\u0391\u03a3\u0301",
         "\u0391\u03a3\u00ad", "I", "\u0131", "\u01f0", "\u0149", "\ufb01", "\u01c8", "\u2167", "\u1f88", "\u212a",
         "\u212b", "\U00010400", "\u038c\u03a3\u039f\u03a3", "\u03a3\u03a3", "", "Acme CORP", "\u00c9COLE"]
ORDER = ["\uff5e", "\U0001F600", "a", "\ud7ff", "\ue000", "\uffff", "\U00010000", "", "abc", "ab", "\u00e9", "\U0010ffff"]
cases = {"lower": [{"input": s, "expected": s.lower()} for s in LOWER], "order": sorted(ORDER)}
os.makedirs("/tmp/fixtures-graph-a", exist_ok=True)
with open("/tmp/fixtures-graph-a/lower_cases.json", "w", encoding="utf-8") as f:
    json.dump(cases, f, ensure_ascii=True, indent=1)
print("lower cases:", len(cases["lower"]), "| order cases:", len(cases["order"]))
