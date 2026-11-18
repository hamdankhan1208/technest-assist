"""Named evaluation cases for policy and product-spec RAG behavior."""

from rag_evaluation import EvaluationCase

EVALUATION_CASES = (
    EvaluationCase(
        name="hardware warranty",
        question="How long is the hardware warranty?",
        expected_sources=("warranty_policy.docx",),
        expected_answer_terms=("2-year",),
    ),
    EvaluationCase(
        name="extended support",
        question="Is an extended support package available?",
        expected_sources=("warranty_policy.docx",),
        expected_answer_terms=("upon request",),
    ),
    EvaluationCase(
        name="unopened return window",
        question="When can I return an unopened item?",
        expected_sources=("returns_policy.docx",),
        expected_answer_terms=("30 days",),
    ),
    EvaluationCase(
        name="defective merchandise",
        question="How long do I have to exchange or refund defective merchandise?",
        expected_sources=("returns_policy.docx",),
        expected_answer_terms=("14 days", "delivery"),
        forbidden_answer_terms=("30 days",),
    ),
    EvaluationCase(
        name="delivery speed",
        question="How long does standard ground shipping take?",
        expected_sources=("delivery_policy.docx",),
        expected_answer_terms=("3-5", "business days"),
    ),
    EvaluationCase(
        name="warranty summary",
        question="Summarize the warranty policy.",
        expected_sources=("warranty_policy.docx",),
        expected_answer_terms=("warranty",),
    ),
    EvaluationCase(
        "returns summary",
        "Summarize the returns and refund policy.",
        expected_sources=("returns_policy.docx",),
    ),
    EvaluationCase(
        "delivery summary",
        "Summarize the delivery and shipping policy.",
        expected_sources=("delivery_policy.docx",),
    ),
    EvaluationCase(
        "all policy summary",
        "Summarize the main policies from the documents.",
        expected_sources=(
            "warranty_policy.docx",
            "returns_policy.docx",
            "delivery_policy.docx",
        ),
    ),
    EvaluationCase(
        name="unsupported promotions",
        question="Do you offer checkout promotions?",
        should_abstain=True,
    ),
    EvaluationCase(
        name="opened item paraphrase",
        question="What is the return policy for opened items?",
        expected_sources=("returns_policy.docx",),
        expected_answer_terms=("unopened",),
        forbidden_answer_terms=("14 days",),
    ),
    EvaluationCase(
        name="unavailable policy summary",
        question="Summarize the promotions policy.",
        should_abstain=True,
    ),
    EvaluationCase(
        name="monitor product code",
        question="What is the product code for the TechView 33-inch Ultrawide Display?",
        expected_sources=("TN-MON-0002.pdf",),
        expected_answer_terms=("TN-MON-0002",),
    ),
    EvaluationCase(
        name="monitor category",
        question="What category is the TechView 33-inch Ultrawide Display?",
        expected_sources=("TN-MON-0002.pdf",),
        expected_answer_terms=("Monitor",),
    ),
)
