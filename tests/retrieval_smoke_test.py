import logging
from habitantes.domain.tools import hybrid_search
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_retrieval_smoke():
    """Smoke test to verify retrieval quality with updated hybrid search (FastEmbed BM25)."""
    load_dotenv()

    # Sample queries covering different categories
    test_cases = [
        {
            "query": "Como renovar o titre de séjour?",
            "expected_category": "Visa & Residency",
            "keywords": ["titre", "séjour", "renov", "préfecture"],
        },
        {
            "query": "Onde abrir conta no banco?",
            "expected_category": "Banking & Finance",
            "keywords": ["banco", "conta", "LCL", "Société Générale", "BoursoBank"],
        },
        {
            "query": "Como pedir o CAF?",
            "expected_category": "Housing & CAF",
            "keywords": ["CAF", "APL", "auxílio", "aluguel"],
        },
        {
            "query": "Médico do trabalho em Grenoble",
            "expected_category": "Health & Insurance",
            "keywords": ["médico", "saúde", "doctolib"],
        },
    ]

    passed = 0
    total = len(test_cases)

    logger.info(f"Starting retrieval smoke test with {total} cases...")

    for case in test_cases:
        query = case["query"]
        logger.info(f"Testing query: '{query}'")

        result = hybrid_search(query=query, top_k=5)

        if "error" in result:
            logger.error(f"Search failed for '{query}': {result['error']['message']}")
            continue

        chunks = result.get("chunks", [])
        if not chunks:
            logger.warning(f"No results found for '{query}'")
            continue

        # Check if at least one result has the expected category or keywords
        found_category = any(
            c.get("category") == case["expected_category"] for c in chunks
        )

        found_keyword = False
        all_texts = " ".join(
            [
                c.get("text", "").lower() + " " + c.get("question", "").lower()
                for c in chunks
            ]
        )
        for kw in case["keywords"]:
            if kw.lower() in all_texts:
                found_keyword = True
                break

        if found_category or found_keyword:
            logger.info(f"SUCCESS: Found relevant results for '{query}'")
            passed += 1
        else:
            logger.warning(f"FAILURE: Results for '{query}' seem irrelevant.")
            for i, c in enumerate(chunks):
                logger.debug(
                    f"  [{i}] Cat: {c.get('category')} | Score: {c.get('score'):.4f}"
                )

    logger.info(f"Smoke test finished: {passed}/{total} passed.")
    assert passed > 0, "Retrieval smoke test failed: 0 cases passed."


if __name__ == "__main__":
    test_retrieval_smoke()
