from duckduckgo_search import DDGS
try:
    from duckduckgo_search import AsyncDDGS
    print("AsyncDDGS available")
except ImportError:
    print("AsyncDDGS not available")

results = DDGS().images("pizza food", max_results=2)
for r in results:
    print(r.get("image"))
