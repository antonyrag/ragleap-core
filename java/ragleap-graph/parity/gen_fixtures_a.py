# Generates parity fixtures for slice (a) by running the real Python code.
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
# Then run this script with /usr/bin/python3; it writes /tmp/fixtures-graph-a/cases.json.
# Use it with: RAGLEAP_GRAPH_PARITY_DIR=/tmp/fixtures-graph-a mvn test (in java/ragleap-graph).
import json, os, sys
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
print("module:", rg.__file__)
assert rg.__file__.startswith(SRC), "wrong module path"
g = rg.GraphIndex(config=rg.GraphConfig(uri="bolt://localhost:1", user="x", password="x"))
assert g.driver is None
OUT = "/tmp/fixtures-graph-a"
os.makedirs(OUT, exist_ok=True)
cases = {"normalize": [], "extract": [], "composite_key": []}
NORM = [
    "", None, "ab", "abc", "  (Acme Corp).  ", "Acme   Corp\n\tInc", "Acme\u00a0Corp", "acme\u2003corp\u3000inc",
    "acme\x1ccorp\x1fx", "acme\x85corp", "ALARA", "IAEA", "ALARA-2", "A1B", "123", "12 ab", "acme corp", "ACME corp",
    "aCmE cOrP", "\u00c9COLE polytechnique", "\u00c9COLE", "stra\u00dfe nord", "\u01c6ungla bay", "\u0130stanbul town",
    "\u03a3\u03af\u03c3\u03c5\u03c6\u03bf\u03c2 group", "\u0391\u03a3 corp", "o'neil and sons", "'quoted name'",
    "\"Quoted Name\"", "((((x))))", "[Acme] {Corp}", "Acme, Corp;", "a" * 3, "A" * 200, "ab " * 80, "\u00e9" * 130,
    "\U0001F600" * 130, "x\U0001F600y z", "caf\u00e9 \u00e9COLE", "\u01c5 title", "i\u0307stanbul", "\u0149abc def",
    "\ufb01nance corp", "\u01f0abc xyz", "tab\tseparated\nname", "\x0b\x0cvt ff name", "\u200bzero width",
    "Dr. Smith", "cafe\u0301 corp", "\u1e9e big", "\u03c3 \u03c2 \u03a3",
]
for s in NORM:
    cases["normalize"].append({"input": s, "expected": g._normalize_entity_name(s)})
TEXTS = [
    "", "The IAEA published new guidelines.", "Acme Corp signed a deal with Globex Industries.",
    "What did Acme Corp launch?", "Who is Alice Smith and where is Bob Jones?", "This That These Those",
    "Acme Corp is great. Acme Corp is really great.", "ACME CORP and Acme Corp and acme corp",
    "NASA-X1 and COVID-19 and U.S. policy", "NASA-x and ABC-_ and ABC-", "ABC123 and ABC and abc", "ACME_corp Acme_Corp",
    "Acme\u00a0Corp\u00a0Inc met Globex\u2003Industries", "Acme\x1cCorp and Globex\x85Industries",
    "\u00e9Acme Corp and Acme Corp\u00e9", "Cafe\u0301 Corp and Acme\u0301 Corp",
    "\u00dcnal Corp and Zo\u00eb Smith", "Alice Bob Carol Dave Erin", "Alice Bob Carol Dave",
    "AB CD EF GH IJ KL MN OP QR ST UV WX YZ AA BB", "word " * 5 + "Acme Corp",
    "Radiation safety and radiation Safety", "line one\nAcme Corp\n\nGlobex Industries",
    "The Quick Brown Fox Jumps Over The Lazy Dog", "Is Are Was Were Do Does Did Can Could Would Should Will May Might",
    "IAEA-2024 report from ICRP-103 and WHO", "Mr. Anderson of Acme-Corp Ltd.", "St Louis Zoo and Los Angeles Times",
    "ALLCAPS WORDS AND MixedCase Words", "\U0001F600 Acme Corp \U0001F600", "\U0001D49CAcme Corp", "Acme\u0661 Corp",
]
OPTS = [
    {"max_entities": 12, "domain_terms": None},
    {"max_entities": 3, "domain_terms": None},
    {"max_entities": 0, "domain_terms": None},
    {"max_entities": 12, "domain_terms": ["radiation safety", "Acme", "xyz not present", ""]},
    {"max_entities": 1, "domain_terms": []},
]
for t in TEXTS:
    for o in OPTS:
        exp = g._extract_entity_candidates_from_text(t, max_entities=o["max_entities"], domain_terms=o["domain_terms"])
        cases["extract"].append({"text": t, "max_entities": o["max_entities"], "domain_terms": o["domain_terms"], "expected": exp})
    cases["extract"].append({"text": t, "max_entities": 10, "domain_terms": None, "via_query": True,
                             "expected": g.extract_query_entities(t)})
CK = [
    ("a", "b", "c"), ("",), ("", "", ""), ("\u00e9", "\u65e5\u672c", "\U0001F600"), ("a\x00b", "c"), ("a", "b\x00c"),
    ("ns", "user", "doc-1"), ("ns", "user", "doc-1", "Acme", "Globex"), ("x" * 1000,),
]
for parts in CK:
    cases["composite_key"].append({"parts": list(parts), "expected": rg._composite_key(*parts)})
cases["constants"] = {"MAX_ALLOWED_DEPTH": rg.MAX_ALLOWED_DEPTH, "stopwords": sorted(rg._SENTENCE_INITIAL_STOPWORDS)}
with open(OUT + "/cases.json", "w", encoding="utf-8") as f:
    json.dump(cases, f, ensure_ascii=True, indent=1)
print({k: len(v) for k, v in cases.items() if isinstance(v, list)})
