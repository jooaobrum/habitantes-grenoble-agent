"""Evaluation metrics for retrieval and generation."""

import re
from typing import Optional

from openai import OpenAI
from sentence_transformers import SentenceTransformer, util


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    """Fraction of relevant docs found in top-k retrieved.

    Formula: (Unique relevant docs in top-k) / (Total unique relevant docs)
    """
    if not relevant_ids:
        return 0.0

    retrieved_k = set(retrieved_ids[:k])
    relevant_set = set(relevant_ids)

    found = retrieved_k.intersection(relevant_set)
    return len(found) / len(relevant_set)


def hit_rate_at_k(
    retrieved_ids: list[str], relevant_ids: list[str], k: int = 5
) -> float:
    """Check if at least one relevant doc is in top-k.

    Returns 1.0 if any relevant doc is found, 0.0 otherwise.
    Useful for RAG where a single good document might be sufficient.
    """
    if not relevant_ids:
        return 0.0

    retrieved_k = set(retrieved_ids[:k])
    relevant_set = set(relevant_ids)

    return 1.0 if retrieved_k.intersection(relevant_set) else 0.0


def context_precision(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """Average Precision (AP) for retrieval.

    Measures the precision at each rank that contains a relevant document,
    then averages these values. Higher scores mean relevant docs are ranked higher.

    Formula: (Sum of P@i for i where item i is relevant) / (Total relevant docs)
    """
    if not relevant_ids or not retrieved_ids:
        return 0.0

    relevant_set = set(relevant_ids)
    seen_relevant = set()
    sum_precisions = 0.0
    relevant_count = 0

    for i, rid in enumerate(retrieved_ids):
        if rid in relevant_set and rid not in seen_relevant:
            relevant_count += 1
            seen_relevant.add(rid)
            precision_at_i = relevant_count / (i + 1)
            sum_precisions += precision_at_i

    if relevant_count == 0:
        return 0.0

    # Standard AP is divided by total relevant items
    return sum_precisions / len(relevant_set)


# ── Layer 2: E2E Metrics (LLM-as-judge & Embedding Similarity) ────────────────


_client: Optional[OpenAI] = None
_embed_model: Optional[SentenceTransformer] = None


def _get_client() -> OpenAI:
    """Lazy-load OpenAI client using project settings."""
    global _client
    if _client is None:
        # Import inside function to avoid circular dependencies if any
        from habitantes.config import load_settings

        settings = load_settings()
        # Use direct API key from settings
        _client = OpenAI(api_key=settings.llm.openai_api_key)
    return _client


def _get_embed_model() -> SentenceTransformer:
    """Lazy-load SentenceTransformer model for similarity."""
    global _embed_model
    if _embed_model is None:
        from habitantes.config import load_settings

        settings = load_settings()
        _embed_model = SentenceTransformer(settings.llm.embedding_model_name)
    return _embed_model


def _parse_llm_score(text: str) -> float:
    """Extract first float found in text, clamped between 0.0 and 1.0."""
    try:
        # Find first number (possibly with dot) in text
        match = re.search(r"(\d+\.\d+|\d+)", text)
        if not match:
            return 0.0
        score = float(match.group(1))
        return max(0.0, min(1.0, score))
    except (ValueError, AttributeError):
        return 0.0


def answer_relevance(question: str, answer: str) -> float:
    """LLM judges if the answer addresses the question. Returns 0.0–1.0."""
    client = _get_client()

    prompt = f"""
    You are an impartial judge evaluation a RAG chatbot answer.
    Question: {question}
    Answer: {answer}

    Score the relevance of the answer to the question on a scale from 0.0 to 1.0.
    1.0 means the answer perfectly and completely addresses the question.
    0.0 means the answer is irrelevant or doesn't address the core request at all.

    Return ONLY a single numeric score.
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    return _parse_llm_score(response.choices[0].message.content or "")


def faithfulness(answer: str, context: list[str]) -> float:
    """LLM judges if every claim in the answer is supported by context. Returns 0.0–1.0."""
    client = _get_client()

    context_text = "\n\n".join(
        [f"Chunk {i + 1}:\n{chunk}" for i, chunk in enumerate(context)]
    )

    prompt = f"""
    You are an impartial judge evaluating if an answer is faithful to the provided context.

    Context:
    {context_text}

    Answer:
    {answer}

    Score the faithfulness from 0.0 to 1.0.
    1.0 means every claim in the answer is strictly supported by the provided context chunks.
    0.0 means the answer contains significant hallucinations or information not present in the context.

    Note: If the answer correctly states that it cannot find information in the context, it is FAITHFUL (1.0).

    Return ONLY a single numeric score.
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    return _parse_llm_score(response.choices[0].message.content or "")


def semantic_similarity(answer: str, reference: str) -> float:
    """Cosine similarity between answer and reference embeddings. Returns 0.0–1.0."""
    if not answer or not reference:
        return 0.0

    model = _get_embed_model()

    # E5 models require 'query: ' prefix for comparison tasks
    embeddings = model.encode([f"query: {answer}", f"query: {reference}"])

    # util.cos_sim returns a matrix
    score = util.cos_sim(embeddings[0], embeddings[1])

    # Convert from tensor/numpy to float
    return float(score.item())
