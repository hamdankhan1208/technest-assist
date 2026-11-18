"""Repeatable evaluation helpers for the TechNest policy RAG flow."""

import argparse
from dataclasses import dataclass
from typing import Callable, Sequence

from policy_rag import PolicyRAG, answer_question, generate_response


@dataclass(frozen=True)
class EvaluationCase:
    """One expected retrieval and answer behavior."""

    name: str
    question: str
    expected_sources: tuple[str, ...] = ()
    expected_answer_terms: tuple[str, ...] = ()
    forbidden_answer_terms: tuple[str, ...] = ()
    should_abstain: bool = False


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome and diagnostics for one evaluation case."""

    case: EvaluationCase
    answer: str
    retrieved_sources: tuple[str, ...]
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationSummary:
    """Aggregate metrics for a complete evaluation run."""

    total: int
    passed: int
    retrieval_recall: float
    citation_recall: float
    abstention_accuracy: float
    answer_grounding: float


def evaluate_answer(
    rag: PolicyRAG,
    case: EvaluationCase,
    response_generator: Callable[[Sequence[dict[str, str]]], str] = generate_response,
) -> EvaluationResult:
    """Run one case and report answer, citation, retrieval, and abstention checks."""
    from policy_rag import (
        ABSTENTION,
        MIN_RELEVANCE_SCORE,
        _is_policy_summary_request,
        _select_summary_chunks,
    )

    if _is_policy_summary_request(case.question):
        chunks = _select_summary_chunks(case.question, rag.get_all_chunks())
        retrieved_sources = tuple(dict.fromkeys(chunk.source for chunk in chunks))
    else:
        results = rag.search(case.question)
        retrieved_sources = tuple(
            dict.fromkeys(
                result.source
                for result in results
                if result.score >= MIN_RELEVANCE_SCORE
            )
        )

    answer = answer_question(rag, case.question, response_generator)
    failures = []

    if case.should_abstain:
        if answer != ABSTENTION:
            failures.append("expected abstention")
    else:
        if answer == ABSTENTION:
            failures.append("expected a supported answer")

    missing_terms = [
        term
        for term in case.expected_answer_terms
        if term.lower() not in answer.lower()
    ]
    if missing_terms:
        failures.append("missing answer terms: " + ", ".join(missing_terms))

    missing_sources = [
        source for source in case.expected_sources if f"[{source}]" not in answer
    ]
    if missing_sources:
        failures.append("missing citations: " + ", ".join(missing_sources))

    missing_retrieval = [
        source for source in case.expected_sources if source not in retrieved_sources
    ]
    if missing_retrieval:
        failures.append("missing retrieved sources: " + ", ".join(missing_retrieval))

    forbidden_terms = [
        term for term in case.forbidden_answer_terms if term.lower() in answer.lower()
    ]
    if forbidden_terms:
        failures.append("unsupported terms: " + ", ".join(forbidden_terms))

    return EvaluationResult(
        case=case,
        answer=answer,
        retrieved_sources=retrieved_sources,
        passed=not failures,
        failures=tuple(failures),
    )


def run_evaluation(
    rag: PolicyRAG,
    cases: Sequence[EvaluationCase],
    response_generator: Callable[[Sequence[dict[str, str]]], str] = generate_response,
) -> list[EvaluationResult]:
    """Run a sequence of evaluation cases in order."""
    if not cases:
        raise ValueError("Evaluation cases must not be empty.")
    return [evaluate_answer(rag, case, response_generator) for case in cases]


def summarize_evaluation(results: Sequence[EvaluationResult]) -> EvaluationSummary:
    """Calculate recall and abstention metrics from evaluation results."""
    if not results:
        raise ValueError("Evaluation results must not be empty.")

    from policy_rag import ABSTENTION

    retrieval_expected = 0
    retrieval_found = 0
    citation_expected = 0
    citation_found = 0
    abstention_expected = 0
    abstention_correct = 0
    grounded_expected = 0
    grounded_correct = 0

    for result in results:
        if result.case.should_abstain:
            abstention_expected += 1
            if result.answer == ABSTENTION:
                abstention_correct += 1
        else:
            grounded_expected += 1
            if result.answer != ABSTENTION:
                grounded_correct += 1

        for source in result.case.expected_sources:
            retrieval_expected += 1
            if source in result.retrieved_sources:
                retrieval_found += 1

            citation_expected += 1
            if f"[{source}]" in result.answer:
                citation_found += 1

    def ratio(found: int, expected: int) -> float:
        return found / expected if expected else 1.0

    return EvaluationSummary(
        total=len(results),
        passed=sum(result.passed for result in results),
        retrieval_recall=ratio(retrieval_found, retrieval_expected),
        citation_recall=ratio(citation_found, citation_expected),
        abstention_accuracy=ratio(abstention_correct, abstention_expected),
        answer_grounding=ratio(grounded_correct, grounded_expected),
    )


def format_evaluation_summary(summary: EvaluationSummary) -> str:
    """Format aggregate metrics for terminal or test output."""
    return (
        f"Cases: {summary.passed}/{summary.total} passed\n"
        f"Retrieval recall: {summary.retrieval_recall:.1%}\n"
        f"Citation recall: {summary.citation_recall:.1%}\n"
        f"Abstention accuracy: {summary.abstention_accuracy:.1%}\n"
        f"Answer grounding: {summary.answer_grounding:.1%}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Index configured documents and run the named evaluation suite."""
    parser = argparse.ArgumentParser(
        description="Evaluate TechNest policy RAG quality."
    )
    parser.add_argument(
        "--include-pdfs",
        action="store_true",
        help="Index product PDFs and include PDF datasheet cases.",
    )
    args = parser.parse_args(argv)

    from rag_evaluation_cases import EVALUATION_CASES
    from policy_rag import _build_rag, _check_ollama_fallback

    rag = _build_rag()
    try:
        rag.index(include_pdfs=args.include_pdfs)
        _check_ollama_fallback()

        cases = EVALUATION_CASES
        if not args.include_pdfs:
            cases = tuple(
                case
                for case in cases
                if not any(source.endswith(".pdf") for source in case.expected_sources)
            )

        results = run_evaluation(rag, cases)
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.case.name}")
            if result.failures:
                for failure in result.failures:
                    print(f"  - {failure}")

        summary = summarize_evaluation(results)
        print("\n" + format_evaluation_summary(summary))
        return 0 if summary.passed == summary.total else 1
    except (RuntimeError, ValueError, OSError) as error:
        print(f"RAG evaluation failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
