# Generates parity recordings for the graph query methods by running the real Python code against a fake driver
# that records every Cypher statement and parameter and returns scripted rows; the return values and the audit
# events are recorded too.
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, os, sys
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"

class Rec:
    def __init__(self):
        self.events = []
    def log(self, **kw):
        self.events.append({"user_id": kw.get("user_id"), "namespace": kw.get("namespace"),
                            "action": kw.get("action"), "document_id": kw.get("document_id"),
                            "entity_count": kw.get("entity_count"), "detail": kw.get("detail")})
    def close(self):
        pass

class QSession:
    def __init__(self, drv):
        self.drv = drv
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def run(self, query, **params):
        self.drv.calls.append({"cypher": "".join(query.split()), "params": params})
        key = "pair" if "PairWeight" in query else ("relation" if "RelationWeight" in query else "default")
        return [dict(r) for r in self.drv.rows.get(key, [])]

class QDriver:
    def __init__(self, rows):
        self.calls = []
        self.rows = rows
    def session(self):
        return QSession(self)
    def close(self):
        pass

DEFAULTS = {
    "search_related_entities": dict(entity_names=[], namespace=None, user_id=None, max_depth=2, limit=10),
    "find_relations": dict(entity_name="", relation_type=None, namespace=None, user_id=None, limit=25, direction="outgoing"),
    "find_lineage": dict(entity_a="", entity_b="", relation_type=None, namespace=None, user_id=None, limit=25),
    "find_entities_by_type": dict(entity_type="", namespace=None, user_id=None, limit=25),
    "find_documents_by_entities": dict(entity_names=[], namespace=None, user_id=None, limit=25),
    "document_entities": dict(document_id="", namespace=None, user_id=None),
}

def C(name, method, rows=None, no_driver=False, **kw):
    args = dict(DEFAULTS[method])
    args.update(kw)
    return {"name": name, "method": method, "args": args, "rows": rows or {}, "no_driver": no_driver}

S = []
rel = {"default": [
    {"entity_id": "globex industries", "entity_name": "Globex Industries", "relationship": "CO_OCCURS_WITH", "depth": 1},
    {"entity_id": "initech", "entity_name": "Initech", "relationship": "CONTAINS", "depth": 2},
    {"entity_id": "x", "entity_name": None, "relationship": "RELATES_AS", "depth": 3}]}
M = "search_related_entities"
S += [
    C("related_basic", M, rows=rel, entity_names=["Acme Corp"], namespace="ns1"),
    C("related_user_depth3_limit0", M, rows=rel, entity_names=["acme corp", "ACME CORP", "  ", "ab", "Globex"], user_id="u1", max_depth=3, limit=0),
    C("related_depth10", M, rows=rel, entity_names=["Acme Corp"], max_depth=10, limit=100),
    C("related_depth0", M, rows=rel, entity_names=["Acme Corp"], max_depth=0),
    C("related_depth11", M, rows=rel, entity_names=["Acme Corp"], max_depth=11),
    C("related_depth_negative", M, rows=rel, entity_names=["Acme Corp"], max_depth=-3),
    C("related_no_names", M, rows=rel, entity_names=[]),
    C("related_all_invalid_names", M, rows=rel, entity_names=["ab", "", "  "]),
    C("related_unicode", M, rows=rel, entity_names=["\u00c9ole Corp", "\U0001F600 corp", "stra\u00dfe nord"]),
    C("related_no_driver", M, no_driver=True, entity_names=["Acme Corp"]),
    C("related_no_driver_bad_depth", M, no_driver=True, entity_names=["Acme Corp"], max_depth=0),
]
fr = {"default": [
    {"subject": "Acme Corp", "relation_type": "PARTNERED_WITH", "object": "Globex Industries", "weight": 2.0},
    {"subject": "Acme Corp", "relation_type": "REPORTED", "object": "Initech", "weight": 1.5}]}
M = "find_relations"
for d in ("outgoing", "incoming", "both"):
    S.append(C("relations_" + d, M, rows=fr, entity_name="Acme Corp", direction=d, namespace="n", user_id="u", limit=7))
S += [
    C("relations_type_filter", M, rows=fr, entity_name="Acme Corp", relation_type="PARTNERED_WITH"),
    C("relations_normalizes", M, rows=fr, entity_name="  ACME   corp. "),
    C("relations_blank", M, rows=fr, entity_name="   "),
    C("relations_short", M, rows=fr, entity_name="ab"),
    C("relations_bad_direction", M, rows=fr, entity_name="Acme Corp", direction="sideways"),
    C("relations_none_direction", M, rows=fr, entity_name="Acme Corp", direction=None),
    C("relations_no_rows", M, entity_name="Acme Corp"),
    C("relations_no_driver", M, no_driver=True, entity_name="Acme Corp"),
    C("relations_limit_zero", M, rows=fr, entity_name="Acme Corp", limit=0),
    C("relations_unicode", M, rows=fr, entity_name="\u00c9COLE polytechnique"),
]
ln = {"pair": [{"document_id": "d1", "weight": 1.0}, {"document_id": "d2", "weight": 2.0}],
      "relation": [{"document_id": "d1", "relation_name": "PARTNERED_WITH", "weight": 1.0}]}
M = "find_lineage"
S += [
    C("lineage_basic", M, rows=ln, entity_a="Acme Corp", entity_b="Globex Corp", namespace="n"),
    C("lineage_truncated", M, rows=ln, entity_a="Acme Corp", entity_b="Globex Corp", limit=2),
    C("lineage_limit_zero", M, rows=ln, entity_a="Acme Corp", entity_b="Globex Corp", limit=0),
    C("lineage_relation_type", M, rows=ln, entity_a="Acme Corp", entity_b="Globex Corp", relation_type="PARTNERED_WITH", user_id="u"),
    C("lineage_raw_lower_no_strip", M, rows=ln, entity_a="ACME CORP", entity_b="  Globex  "),
    C("lineage_blank_a", M, rows=ln, entity_a="  ", entity_b="Globex"),
    C("lineage_blank_b", M, rows=ln, entity_a="Acme", entity_b=""),
    C("lineage_unicode", M, rows=ln, entity_a="\u0391\u03a3 Corp", entity_b="\u0130stanbul"),
    C("lineage_no_rows", M, entity_a="Acme Corp", entity_b="Globex Corp"),
    C("lineage_no_driver", M, no_driver=True, entity_a="Acme Corp", entity_b="Globex Corp"),
]
bt = {"default": [{"entity_id": "acme corp", "entity_name": "Acme Corp", "entity_type": "ORG"},
                  {"entity_id": "bob", "entity_name": "Bob", "entity_type": "Org"}]}
M = "find_entities_by_type"
S += [
    C("type_basic", M, rows=bt, entity_type="org", namespace="n"),
    C("type_unstripped", M, rows=bt, entity_type="  ORG  ", limit=5, user_id="u"),
    C("type_empty", M, rows=bt, entity_type=""),
    C("type_blank", M, rows=bt, entity_type="   "),
    C("type_no_driver", M, no_driver=True, entity_type="ORG"),
    C("type_no_rows", M, entity_type="X"),
]
docs = {"default": [
    {"document_id": "d1", "document_name": "Doc One", "matched_entities": 2, "graph_score": 3.5, "matched_entity_names": ["Acme Corp", "Globex"]},
    {"document_id": 7, "document_name": None, "matched_entities": 1, "graph_score": 0.0, "matched_entity_names": []},
    {"document_id": None, "document_name": "", "matched_entities": 0, "graph_score": 0.0, "matched_entity_names": None}]}
M = "find_documents_by_entities"
S += [
    C("docs_basic", M, rows=docs, entity_names=["Acme Corp", "acme corp", "Globex"], namespace="ns"),
    C("docs_user_limit", M, rows=docs, entity_names=["Acme Corp"], user_id="u", limit=0),
    C("docs_none_valid", M, rows=docs, entity_names=["ab"]),
    C("docs_no_driver", M, no_driver=True, entity_names=["Acme Corp"]),
]
de = {"default": [{"entity_id": "acme corp", "entity_name": "Acme Corp"}, {"entity_id": None, "entity_name": None}]}
M = "document_entities"
S += [
    C("docents_basic", M, rows=de, document_id="d1", namespace="ns"),
    C("docents_user", M, rows=de, document_id="d2", user_id="u"),
    C("docents_no_driver", M, no_driver=True, document_id="d1"),
]
g = rg.GraphIndex(config=rg.GraphConfig(uri="bolt://localhost:1", user="x", password="x"))
assert g.driver is None
out = []
for sc in S:
    rec = Rec()
    g._audit = rec
    drv = None if sc["no_driver"] else QDriver(sc["rows"])
    g.driver = drv
    try:
        res = getattr(g, sc["method"])(**sc["args"])
        raised = None
    except ValueError as e:
        res, raised = None, str(e)
    out.append({"name": sc["name"], "method": sc["method"], "args": sc["args"], "rows": sc["rows"],
                "no_driver": sc["no_driver"], "expected": {"result": res, "raises": raised},
                "calls": drv.calls if drv else [], "audit": rec.events})
OUT = "/tmp/fixtures-graph-a"
os.makedirs(OUT, exist_ok=True)
with open(OUT + "/query_cases.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=True, indent=1)
print("scenarios:", len(out), "| raises:", [o["name"] for o in out if o["expected"]["raises"]])
