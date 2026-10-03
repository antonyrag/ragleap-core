"""
Builds the benchmark corpus for the cross-backend retrieval benchmark (issue #565).

Data: SQuAD v1.1 dev set (Rajpurkar et al., CC BY-SA 4.0). Every 7th paragraph becomes a
document; the first question of each of the first 60 selected paragraphs becomes a query
whose "gold" document is the paragraph it was written from. Everything is embedded once
with a local Ollama model, so every vector database receives identical vectors.

Usage: python3 prepare_dataset.py            (writes $BENCH_DIR/corpus.json, default /tmp/bench)
       python3 prepare_dataset.py --force    (rebuild even if corpus.json exists)
"""
import json
import os
import sys
import time
import urllib.request

OUT = os.environ.get("BENCH_DIR", "/tmp/bench")
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
SQUAD_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v1.1.json"
STEP = 7
N_QUERIES = 60
BATCH = 8


def post(path, payload, timeout=600):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def embed(texts):
    try:
        return post("/api/embed", {"model": MODEL, "input": texts})["embeddings"]
    except Exception as e:  # older Ollama without /api/embed
        print("  /api/embed failed (%s), falling back to /api/embeddings" % e, file=sys.stderr)
        return [post("/api/embeddings", {"model": MODEL, "prompt": t})["embedding"] for t in texts]


def main():
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "corpus.json")
    if os.path.exists(target) and "--force" not in sys.argv:
        print("corpus.json already exists, use --force to rebuild:", target)
        return
    squad_path = os.path.join(OUT, "dev-v1.1.json")
    if not os.path.exists(squad_path):
        print("downloading SQuAD dev set ...")
        urllib.request.urlretrieve(SQUAD_URL, squad_path)
    data = json.load(open(squad_path, encoding="utf-8"))["data"]

    paragraphs = []
    for article in data:
        for para in article["paragraphs"]:
            paragraphs.append((article["title"], para))
    docs, queries = [], []
    for i, (title, para) in enumerate(paragraphs):
        if i % STEP != 0:
            continue
        doc_id = "p%d" % i
        docs.append({"id": doc_id, "title": title, "text": para["context"]})
        if len(queries) < N_QUERIES and para["qas"]:
            queries.append({"id": "q%d" % i, "text": para["qas"][0]["question"], "gold": doc_id})
    print("documents=%d queries=%d (from %d paragraphs)" % (len(docs), len(queries), len(paragraphs)))

    started = time.time()
    for kind, items, prefix in (("queries", queries, "search_query: "), ("documents", docs, "search_document: ")):
        for start in range(0, len(items), BATCH):
            chunk = items[start:start + BATCH]
            vectors = embed([prefix + c["text"] for c in chunk])
            for c, v in zip(chunk, vectors):
                c["vec"] = v
            done = min(start + BATCH, len(items))
            if done % 40 == 0 or done == len(items):
                print("  embedded %s %d/%d  (%.0fs elapsed)" % (kind, done, len(items), time.time() - started))
    dim = len(docs[0]["vec"])
    assert all(len(d["vec"]) == dim for d in docs) and all(len(q["vec"]) == dim for q in queries)
    json.dump({"source": "SQuAD v1.1 dev (CC BY-SA 4.0)", "model": MODEL, "dim": dim,
               "docPrefix": "search_document: ", "queryPrefix": "search_query: ",
               "docs": docs, "queries": queries}, open(target, "w", encoding="utf-8"))
    print("wrote %s  dim=%d  size=%.1f MB" % (target, dim, os.path.getsize(target) / 1e6))


if __name__ == "__main__":
    main()
