from datetime import date
import json
from pathlib import Path
import unittest

from pipeline import build_worklist


class WorklistTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / "examples/synthetic-bundle.json"
        self.bundle = json.loads(fixture.read_text())
        self.as_of = date(2026, 1, 1)

    def run_demo(self):
        return build_worklist(self.bundle, self.as_of, 180)

    def test_exercises_all_four_statuses_and_excludes_minor(self):
        rows = {row["patient_id"]: row for row in self.run_demo()}
        self.assertEqual({key: row["status"] for key, row in rows.items()}, {
            "demo-exact": "due_today",
            "demo-missing": "no_eligible_result",
            "demo-overdue": "overdue",
            "demo-pending": "no_eligible_result",
            "demo-recent": "up_to_date",
        })
        self.assertEqual(rows["demo-exact"]["latest_observation_id"], "a1c-exact")
        self.assertIsNone(rows["demo-pending"]["next_due_date"])

    def test_duplicate_resource_policy(self):
        original = self.run_demo()
        resource = self.bundle["entry"][0]["resource"]
        self.bundle["entry"].append({"resource": dict(resource)})
        self.assertEqual(self.run_demo(), original)
        self.bundle["entry"][-1]["resource"]["birthDate"] = "1999-01-01"
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            self.run_demo()

    def test_reference_validation(self):
        self.bundle["entry"][1]["resource"]["subject"]["reference"] = "Patient/absent"
        with self.assertRaisesRegex(ValueError, "Unresolved relative patient reference"):
            self.run_demo()

    def test_result_becomes_available_after_issuance(self):
        rows = build_worklist(self.bundle, date(2026, 1, 3), 180)
        pending = next(row for row in rows if row["patient_id"] == "demo-pending")
        self.assertEqual(pending["status"], "up_to_date")
        self.assertEqual(pending["latest_observation_id"], "a1c-pending")


if __name__ == "__main__":
    unittest.main()
