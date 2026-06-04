from __future__ import annotations

import re

from .models import PaperCandidate

FALLBACK_SIGNAL_RE = re.compile(
    r"\b(agent|agents|multi-agent|agentic|llm|llms|large language model|language model|tool[- ]?use|planning|autonomous|workflow|coding)\b",
    re.IGNORECASE,
)


def build_query(*, keyword: str, date: str, categories: list[str]) -> str:
    start = date.replace("-", "") + "0000"
    end = date.replace("-", "") + "2359"
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    return f"({category_query}) AND (all:{keyword}) AND submittedDate:[{start} TO {end}]"


def build_combined_query(*, keywords: list[str], date: str, categories: list[str]) -> str:
    start = date.replace("-", "") + "0000"
    end = date.replace("-", "") + "2359"
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    keyword_query = " OR ".join(f"all:{keyword}" for keyword in keywords)
    return f"({category_query}) AND ({keyword_query}) AND submittedDate:[{start} TO {end}]"


def infer_priority_keyword(candidate: PaperCandidate, keywords: list[str]) -> tuple[str, int]:
    text = f"{candidate.title} {candidate.abstract}".lower()
    for rank, keyword in enumerate(keywords, start=1):
        if keyword.lower() in text:
            return keyword, rank
    return keywords[0], 1


def listing_candidate_matches(candidate: PaperCandidate, keywords: list[str]) -> bool:
    text = f"{candidate.title} {' '.join(candidate.categories)}"
    return FALLBACK_SIGNAL_RE.search(text) is not None or any(keyword.lower() in text.lower() for keyword in keywords)


def listing_prefilter_score(candidate: PaperCandidate, keywords: list[str]) -> float:
    text = f"{candidate.title} {' '.join(candidate.categories)}".lower()
    score = 0.0
    for rank, keyword in enumerate(keywords, start=1):
        if keyword.lower() in text:
            score += max(0.5, 4.0 - rank)
    if re.search(r"\bagents?\b|multi-agent|agentic", text):
        score += 6.0
    if re.search(r"\bllms?\b|large language model|language model", text):
        score += 4.0
    if re.search(r"\b(reasoning|benchmark|evaluation|skill|distillation|reinforcement|privacy|safety|memory|tool)\b", text):
        score += 2.0
    if any(category in candidate.categories for category in ("cs.AI", "cs.CL", "cs.LG", "stat.ML")):
        score += 1.0
    return score
