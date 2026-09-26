"""Citation validation tests: unsupported evidence IDs are rejected (spec 9)."""

from app.citations import validate_citations
from app.models import Finding, Hypothesis, Recommendation, SynthesisResult


def _synthesis() -> SynthesisResult:
    return SynthesisResult(
        summary="s",
        findings=[
            Finding(statement="f1 keeps one valid id", evidence_ids=["ev_1", "ev_ghost"]),
            Finding(statement="f2 has only invalid ids", evidence_ids=["ev_ghost2"]),
        ],
        hypotheses=[
            Hypothesis(
                statement="h1 mixed",
                confidence=0.8,
                supporting_evidence_ids=["ev_1", "ev_ghost3"],
                contradicting_evidence_ids=["ev_ghost5"],
            ),
            Hypothesis(
                statement="h2 all invalid",
                confidence=0.5,
                supporting_evidence_ids=["ev_ghost4"],
                contradicting_evidence_ids=[],
            ),
        ],
        recommendations=[Recommendation(statement="r", reason="because")],
        missing_information=[],
    )


def test_invalid_ids_rejected_and_reported():
    cleaned, rejected = validate_citations(_synthesis(), {"ev_1"})
    assert set(rejected) == {"ev_ghost", "ev_ghost2", "ev_ghost3", "ev_ghost4", "ev_ghost5"}


def test_finding_without_valid_evidence_is_dropped():
    cleaned, _ = validate_citations(_synthesis(), {"ev_1"})
    assert len(cleaned.findings) == 1
    assert cleaned.findings[0].evidence_ids == ["ev_1"]


def test_hypothesis_ids_cleaned():
    cleaned, _ = validate_citations(_synthesis(), {"ev_1"})
    assert cleaned.hypotheses[0].supporting_evidence_ids == ["ev_1"]
    assert cleaned.hypotheses[0].contradicting_evidence_ids == []


def test_hypothesis_without_support_gets_missing_note():
    cleaned, _ = validate_citations(_synthesis(), {"ev_1"})
    assert any("without valid supporting evidence" in note for note in cleaned.missing_information)


def test_all_valid_ids_untouched():
    synthesis = SynthesisResult(
        summary="s",
        findings=[Finding(statement="f", evidence_ids=["ev_1", "ev_2"])],
        hypotheses=[],
        recommendations=[],
        missing_information=[],
    )
    cleaned, rejected = validate_citations(synthesis, {"ev_1", "ev_2"})
    assert rejected == []
    assert cleaned.findings[0].evidence_ids == ["ev_1", "ev_2"]