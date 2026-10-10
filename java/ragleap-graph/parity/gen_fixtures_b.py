# Generates upsert recordings for the Java parity test by running the real Python _upsert_document_once
# against a fake driver that records every Cypher statement and its parameters.
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, os, sys
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"

class FakeSession:
    def __init__(self, drv):
        self.drv = drv
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def run(self, query, **params):
        self.drv.calls.append({"cypher": "".join(query.split()), "params": params})
        if "RETURN pw.entity_a AS a" in query:
            return [{"a": a, "b": b} for a, b in self.drv.old_pairs]
        if "RETURN rw.subject AS subject" in query:
            return [{"subject": s, "relation_type": t, "object": o} for s, t, o in self.drv.old_relations]
        return []

class FakeDriver:
    def __init__(self, old_pairs, old_relations):
        self.calls = []
        self.old_pairs = [tuple(x) for x in old_pairs]
        self.old_relations = [tuple(x) for x in old_relations]
    def session(self):
        return FakeSession(self)
    def close(self):
        pass

def S(name, **kw):
    d = dict(name=name, document_id="doc-" + name, title="T", chunks=[], namespace=None, user_id=None,
             max_entities=80, max_pairs=150, domain_terms=None, old_pairs=[], old_relations=[])
    d.update(kw)
    return d

corps = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Vandelay", "Stark", "Wayne", "Wonka", "Cyberdyne",
         "Tyrell", "Soylent", "Massive", "Oscorp", "Gringotts", "Duff", "Pied", "Aperture", "Black", "Mesa"]
SCEN = [
    S("basic", title="Basic", chunks=[{"text": "Acme Corp announced a partnership with Globex Industries."}]),
    S("namespace_user", namespace="tenant-1", user_id="u-9",
      chunks=[{"text": "Alice Smith works at Acme Corp. Acme Corp hired Bob Jones."}]),
    S("case_variants", title=None, chunks=[{"text": "Acme Corp and Globex Industries."},
      {"text": "ACME CORP met Globex Industries and Initech Systems."}]),
    S("blank_chunks", chunks=[{"text": ""}, {"text": "   \n"}, {"nottext": "Acme Corp"}, {"text": "Acme Corp Initech"}]),
    S("no_chunks", chunks=[]),
    S("cut_by_max", chunks=[{"text": "Alpha Beta Gamma Delta Epsilon Zeta Eta"}, {"text": "Alpha Beta Gamma"},
      {"text": "Gamma Alpha"}], max_entities=2, max_pairs=1),
    S("many_entities", chunks=[{"text": " ".join(c + " Corp." for c in corps)}]),
    S("many_entities_small_pairs", chunks=[{"text": " ".join(c + " Corp." for c in corps)}], max_pairs=7),
    S("domain_terms", chunks=[{"text": "we discussed radiation safety and acme corp today"}],
      domain_terms=["radiation safety", "Acme Corp"]),
    S("code_point_order", chunks=[{"text": "mention \U0001F600 corp and \uff5e tilde here"}],
      domain_terms=["\U0001F600 corp", "\uff5e tilde"]),
    S("long_name", chunks=[{"text": "mention " + "x" * 130 + " here with Acme Corp"}], domain_terms=["x" * 130]),
    S("old_pairs", chunks=[{"text": "Acme Corp and Globex Industries."}],
      old_pairs=[["acme corp", "globex industries"], ["legacy co", "acme corp"], ["\uff5e tilde", "\U0001F600 corp"]]),
    S("old_relations", chunks=[{"text": "Acme Corp and Globex Industries."}],
      old_relations=[["acme corp", "PARTNERED_WITH", "globex industries"]]),
    S("empty_namespace", namespace="", chunks=[{"text": "Acme Corp and Globex Industries."}]),
]
g = rg.GraphIndex(config=rg.GraphConfig(uri="bolt://localhost:1", user="x", password="x"))
out = []
for sc in SCEN:
    drv = FakeDriver(sc["old_pairs"], sc["old_relations"])
    g.driver = drv
    summary = g._upsert_document_once(
        document_id=sc["document_id"], title=sc["title"], chunks=sc["chunks"], namespace=sc["namespace"],
        user_id=sc["user_id"], max_entities=sc["max_entities"], max_pairs=sc["max_pairs"],
        domain_terms=sc["domain_terms"])
    out.append({"name": sc["name"],
                "args": {k: sc[k] for k in ("document_id", "title", "chunks", "namespace", "user_id",
                                            "max_entities", "max_pairs", "domain_terms")},
                "old_pairs": sc["old_pairs"], "old_relations": sc["old_relations"],
                "summary": summary, "calls": drv.calls})
OUT = "/tmp/fixtures-graph-a"
os.makedirs(OUT, exist_ok=True)
with open(OUT + "/upsert_cases.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=True, indent=1)
print("scenarios:", len(out), "| calls:", [len(o["calls"]) for o in out])
print("summaries:", [(o["name"], o["summary"]["entities_indexed"], o["summary"]["relationships_indexed"], o["summary"]["relations_indexed"]) for o in out])
