from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.evaluation import evaluate
from ragleap_graph.retrieval import GraphRetriever
from eval_graph_compare import GraphRetrieverAskAdapter, compare_retrieval_methods

rag = RagLeap(database_url="...", embedder=..., primary=...)
graph_retriever = GraphRetriever(graph=your_graph_index, rag=rag)

def generate_fn(query, context_str):
    # same LLM call rag.ask() uses internally
    ...

adapter = GraphRetrieverAskAdapter(graph_retriever, generate_fn)

test_cases = [
    {"query": "...", "expected_document": "...", "expected_keywords": [...]},
    # your real labeled test cases
]

results = compare_retrieval_methods(rag, adapter, test_cases, evaluate)
print(results)
