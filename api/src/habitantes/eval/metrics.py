"""Evaluation metrics for retrieval and generation."""

import re
from typing import Optional

from openai import OpenAI
from sentence_transformers import SentenceTransformer, util

# Fixed, product-independent similarity judge. Decoupled from the KB embedding on
# purpose: swapping the retrieval model must not shift the eval metric's scale (and
# thus its gate target). Keep this pinned even though the KB now uses OpenAI.
_SEMANTIC_SIM_MODEL = "intfloat/multilingual-e5-large"


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
_judge_model: Optional[str] = None
_embed_model: Optional[SentenceTransformer] = None


def _get_client() -> OpenAI:
    """Lazy-load OpenAI client using project settings."""
    global _client
    if _client is None:
        # Import inside function to avoid circular dependencies if any
        from habitantes.config import load_settings

        settings = load_settings()
        # Judge is a chat call — route through OpenRouter (embedding path below
        # still uses a local SentenceTransformer, unaffected).
        _client = OpenAI(
            api_key=settings.llm.openrouter_api_key,
            base_url=settings.llm.base_url,
        )
    return _client


def _get_judge_model() -> str:
    """Lazy-load the judge model id from project settings."""
    global _judge_model
    if _judge_model is None:
        from habitantes.config import load_settings

        _judge_model = load_settings().llm.judge_model_name
    return _judge_model


def _get_embed_model() -> SentenceTransformer:
    """Lazy-load the fixed SentenceTransformer used for semantic_similarity."""
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(_SEMANTIC_SIM_MODEL)
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
        model=_get_judge_model(),
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
        model=_get_judge_model(),
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

    score = util.cos_sim(embeddings[0], embeddings[1])

    return float(score.item())


# ── v2-only metrics: deterministic keyword/source checks + non-fabrication judge ──


def keyword_coverage(answer: str, keywords: list[str]) -> float:
    """Fraction of expected keywords found in the answer (case/accent-insensitive substring).

    Deterministic, code-based grader — cheap and interpretable alongside the
    embedding-based semantic_similarity. Returns 0.0 if there are no keywords to check.
    """
    if not keywords:
        return 0.0
    if not answer:
        return 0.0

    answer_norm = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in answer_norm)
    return hits / len(keywords)


def contains_stale_fact(answer: str, stale_markers: list[str]) -> bool:
    """True if the answer repeats a known-outdated fact (case-insensitive substring).

    Deterministic. Used only for `kb_web` cases where the golden dataset records the
    specific stale value (old price, old rule, etc.) that a not-updated answer would
    parrot from the KB chunk or the model's own stale training knowledge.
    """
    if not stale_markers or not answer:
        return False
    answer_norm = answer.lower()
    return any(marker.lower() in answer_norm for marker in stale_markers)


def used_web_source(sources: list[dict]) -> bool:
    """True if any source in the agent's response came from web search.

    Deterministic. Web results are tagged `"category": "Web (Grenoble)"` when appended
    to `state["sources"]` in agent.py (see `web_sources.append(...)` in the ReAct loop).
    Reading it off `sources` avoids adding a new field to `AgentState` just for eval
    purposes — no state/contract change needed.
    """
    return any(s.get("category") == "Web (Grenoble)" for s in sources)


def non_fabrication(question: str, answer: str, context: list[str]) -> float:
    """LLM judges whether the answer avoided fabricating unsupported specifics.

    For negative (`expected_source: none`) cases: out-of-scope questions should be
    declined/redirected, and empty-KB/unknowable questions should get general guidance
    without inventing a specific name, number, date, or live/personal status that isn't
    actually knowable. Returns 0.0-1.0; 1.0 = no fabrication detected.
    """
    client = _get_client()

    context_text = "\n\n".join(context) if context else "(nenhum contexto fornecido)"

    prompt = f"""
    Você é um juiz avaliando se um chatbot comunitário (Habitantes de Grenoble) evitou
    "alucinar" ao responder uma pergunta que NÃO deveria ter uma resposta específica —
    seja porque é fora do escopo (não é sobre Grenoble), seja porque pede um fato/número/
    nome/status específico que nenhuma fonte disponível poderia realmente saber (dado
    ao vivo, informação pessoal, entidade fictícia).

    Pergunta: {question}

    Contexto disponível ao chatbot: {context_text}

    Resposta do chatbot: {answer}

    Dê uma nota de 0.0 a 1.0:
    1.0 = a resposta recusou/redirecionou apropriadamente (se fora de escopo), OU deu
          orientação geral sem inventar um fato específico não suportado (nome, número,
          data, status pessoal/ao vivo).
    0.0 = a resposta inventou um fato, nome, número, data ou status específico que não
          está presente no contexto e não poderia ser conhecido.

    Notas parciais são aceitáveis se a resposta hesitar mas ainda assim inventar um
    detalhe específico não suportado.

    Retorne APENAS um número.
    """.strip()

    response = client.chat.completions.create(
        model=_get_judge_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    return _parse_llm_score(response.choices[0].message.content or "")
