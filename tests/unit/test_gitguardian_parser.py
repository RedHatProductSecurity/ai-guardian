"""Tests for GitGuardian output parser."""

import json
import os
import tempfile
import unittest

from ai_guardian.scanners.output_parsers import GitGuardianOutputParser


class TestGitGuardianOutputParser(unittest.TestCase):

    def setUp(self):
        self.parser = GitGuardianOutputParser()

    def _write_output(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, json.dumps(data).encode("utf-8"))
        os.close(fd)
        return path

    def test_parse_empty_results(self):
        data = {"policy_break_count": 0, "policies": [], "policy_breaks": []}
        path = self._write_output(data)
        result = self.parser.parse(path)
        self.assertIsNotNone(result)
        self.assertFalse(result["has_secrets"])
        self.assertEqual(result["total_findings"], 0)
        os.unlink(path)

    def test_parse_single_policy_break(self):
        data = {
            "policy_break_count": 1,
            "policies": ["Secrets detection"],
            "policy_breaks": [
                {
                    "break_type": "AWS Keys",
                    "policy": "Secrets detection",
                    "validity": "valid_data",
                    "incidents": [
                        {
                            "location": {
                                "filename": "test.txt",
                                "line_start": 5,
                                "line_end": 5,
                            },
                            "type": "aws_access_key_id",
                        }
                    ],
                }
            ],
        }
        path = self._write_output(data)
        result = self.parser.parse(path)
        self.assertTrue(result["has_secrets"])
        self.assertEqual(result["total_findings"], 1)
        finding = result["findings"][0]
        self.assertEqual(finding["rule_id"], "aws_access_key_id")
        self.assertEqual(finding["file"], "test.txt")
        self.assertEqual(finding["line_number"], 5)
        self.assertTrue(finding["verified"])
        os.unlink(path)

    def test_parse_multiple_breaks(self):
        data = {
            "policy_break_count": 2,
            "policies": ["Secrets detection"],
            "policy_breaks": [
                {
                    "break_type": "AWS Keys",
                    "validity": "valid_data",
                    "incidents": [
                        {
                            "location": {
                                "filename": "a.py",
                                "line_start": 1,
                                "line_end": 1,
                            },
                            "type": "aws_key",
                        }
                    ],
                },
                {
                    "break_type": "GitHub Token",
                    "validity": "no_checker",
                    "incidents": [
                        {
                            "location": {
                                "filename": "b.py",
                                "line_start": 10,
                                "line_end": 10,
                            },
                            "type": "github_token",
                        }
                    ],
                },
            ],
        }
        path = self._write_output(data)
        result = self.parser.parse(path)
        self.assertTrue(result["has_secrets"])
        self.assertEqual(result["total_findings"], 2)
        os.unlink(path)

    def test_validity_maps_to_verified(self):
        data = {
            "policy_break_count": 1,
            "policy_breaks": [
                {
                    "break_type": "Test",
                    "validity": "no_checker",
                    "incidents": [
                        {
                            "location": {
                                "filename": "f.py",
                                "line_start": 1,
                                "line_end": 1,
                            },
                            "type": "test_secret",
                        }
                    ],
                }
            ],
        }
        path = self._write_output(data)
        result = self.parser.parse(path)
        self.assertFalse(result["findings"][0]["verified"])
        os.unlink(path)

    def test_parse_nonexistent_file(self):
        result = self.parser.parse("/nonexistent/file.json")
        self.assertIsNone(result)

    def test_parse_invalid_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"not json")
        os.close(fd)
        result = self.parser.parse(path)
        self.assertIsNone(result)
        os.unlink(path)

    def test_parse_error_object_is_not_treated_as_clean(self):
        path = self._write_output({"error": "workspace quota exceeded"})

        result = self.parser.parse(path)

        self.assertIsNone(result)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
