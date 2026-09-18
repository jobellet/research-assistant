"""Regression tests for deterministic manuscript-claim grounding."""
import unittest

from audit_module.claim_auditor import audit_claims


class TestClaimAuditor(unittest.TestCase):
    def test_classifies_supported_review_and_numeric_contradiction(self):
        report = audit_claims(
            "The analysis recorded 120 neurons across 12 sessions. "
            "Accuracy improved by 20%. "
            "The intervention eliminated all adverse events. "
            "We recorded 15 sessions.",
            "The underlying analysis recorded 120 neurons across 12 sessions. "
            "Model accuracy improved by 20%. "
            "3 adverse events occurred during the intervention.",
        )

        self.assertEqual(report["summary"], {
            "supported": 2,
            "needs_review": 1,
            "contradicted": 1,
        })
        self.assertEqual(report["claims"][0]["status"], "supported")
        self.assertEqual(report["claims"][2]["status"], "needs_review")
        self.assertEqual(report["claims"][3]["status"], "contradicted")
        self.assertEqual(report["claims"][3]["claimed_numbers"], ["15"])
        self.assertEqual(report["claims"][3]["evidence_numbers"], ["12", "120"])

    def test_accepts_latex_and_validates_threshold(self):
        report = audit_claims(
            r"The result improved by 20\%. \cite{source}",
            "The result improved by 20%.",
        )
        self.assertEqual(report["summary"]["supported"], 1)
        with self.assertRaises(ValueError):
            audit_claims("A valid claim has words.", "Evidence has words.", min_support_score=1.1)


if __name__ == "__main__":
    unittest.main()
