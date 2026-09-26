"""Citation validation: reject evidence IDs that were never collected.

Core rule (spec Section 2/9): the model may reason about production, but it
must not invent production state. Any evidence ID the model references that
does not exist in the collected evidence is rejected.
"""

from __future__ import annotations

from app.models import SynthesisResult


def validate_citations(
    synthesis: SynthesisResult, valid_ids: set[str]
) -> tuple[SynthesisResult, list[str]]:
    """Strip invalid evidence references. Returns (cleaned, rejected_ids).

    - Findings with no valid evidence left are dropped (factual claims require
      evidence IDs).
    - Hypotheses keep their statements; if all supporting IDs were invalid,
      a note is appended to missing_information.
    """
    rejected: list[str] = []

    findings = []
    for finding in synthesis.findings:
        kept = [eid for eid in finding.evidence_ids if eid in valid_ids]
        rejected.extend(eid for eid in finding.evidence_ids if eid not in valid_ids)
        if kept:
            findings.append(finding.model_copy(update={"evidence_ids": kept}))

    hypotheses = []
    notes: list[str] = []
    for hyp in synthesis.hypotheses:
        supporting = [eid for eid in hyp.supporting_evidence_ids if eid in valid_ids]
        contradicting = [eid for eid in hyp.contradicting_evidence_ids if eid in valid_ids]
        rejected.extend(eid for eid in hyp.supporting_evidence_ids if eid not in valid_ids)
        rejected.extend(
            eid for eid in hyp.contradicting_evidence_ids if eid not in valid_ids
        )
        if not supporting:
            notes.append(
                f"hypothesis retained without valid supporting evidence: {hyp.statement[:120]}"
            )
        hypotheses.append(
            hyp.model_copy(
                update={
                    "supporting_evidence_ids": supporting,
                    "contradicting_evidence_ids": contradicting,
                }
            )
        )

    cleaned = SynthesisResult(
        summary=synthesis.summary,
        findings=findings,
        hypotheses=hypotheses,
        recommendations=synthesis.recommendations,
        missing_information=synthesis.missing_information + notes,
    )
    return cleaned, rejected