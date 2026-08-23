from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scan_repository_secrets import scan_path  # noqa: E402


class RepositorySecretScanTests(unittest.TestCase):
    def test_repository_has_no_secret_values(self) -> None:
        self.assertEqual(scan_path(ROOT), [])

    def test_literal_secret_field_is_reported_without_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.json"
            path.write_text(json.dumps({"api_key": "not-a-real-secret"}))
            findings = scan_path(path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][1], "api_key")
        self.assertNotIn("not-a-real-secret", repr(findings))

    def test_secret_reference_names_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.json"
            path.write_text(json.dumps({"secret_refs": ["SERVICE_API_KEY"]}))
            self.assertEqual(scan_path(path), [])


if __name__ == "__main__":
    unittest.main()
