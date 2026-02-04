import unittest

from mmo.core.report_builders import merge_downmix_qa_issues_into_report


def _issue(
    issue_id: str,
    message: str,
    *,
    evidence_id: str = "EVID.TEST.ISSUE",
    value: object = 1,
    where: dict | None = None,
) -> dict:
    evidence = [{"evidence_id": evidence_id, "value": value}]
    if where is not None:
        evidence[0]["where"] = where
    return {
        "issue_id": issue_id,
        "severity": 50,
        "confidence": 1.0,
        "message": message,
        "target": {"scope": "session"},
        "evidence": evidence,
    }


class TestDownmixQaIssueMerge(unittest.TestCase):
    def test_merge_appends_sorted_and_idempotent(self) -> None:
        existing = _issue("ISSUE.EXISTING", "keep")
        issue_b = _issue("ISSUE.B", "b")
        issue_a2 = _issue("ISSUE.A", "z", value=2)
        issue_a1 = _issue("ISSUE.A", "a", value=1)

        report = {
            "issues": [existing],
            "downmix_qa": {
                "issues": [issue_b, issue_a2, issue_a1],
                "measurements": [],
                "src_path": "",
                "ref_path": "",
                "log": "",
            },
        }

        merge_downmix_qa_issues_into_report(report)
        issues = report["issues"]
        self.assertEqual(issues[0]["issue_id"], "ISSUE.EXISTING")
        self.assertEqual(
            [issue["issue_id"] for issue in issues[1:]],
            ["ISSUE.A", "ISSUE.A", "ISSUE.B"],
        )
        self.assertEqual(
            [issue["message"] for issue in issues[1:]],
            ["a", "z", "b"],
        )

        merge_downmix_qa_issues_into_report(report)
        self.assertEqual(len(report["issues"]), 4)

    def test_merge_no_issues_no_change(self) -> None:
        existing = _issue("ISSUE.EXISTING", "keep")
        report = {"issues": [existing], "downmix_qa": {"issues": []}}
        merge_downmix_qa_issues_into_report(report)
        self.assertEqual(report["issues"], [existing])


if __name__ == "__main__":
    unittest.main()
