#!/usr/bin/env python3
"""Unit tests for the compatibility harness, not a production compiler adapter."""
import json
import re
import unittest
from check_compilers import fields, records, PROFILE, MODES


class CompilerProtocolTests(unittest.TestCase):
    def test_profile_declares_exact_sources_and_current_boundary(self):
        profile = json.loads(PROFILE.read_text())
        self.assertEqual(profile["schema_version"], 1)
        for key in ["base_source", "luce_source"]:
            self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{40}", profile[key]))
        self.assertEqual(profile["modes"], list(MODES))
        self.assertEqual(profile["hosts"], ["arm64-macos", "x86_64-linux"])
        self.assertEqual(profile["manifest"], "luce.toml")
        self.assertEqual(profile["status"], "compatibility_fixture_not_installer")
        self.assertFalse(profile["compiler_source_changes"])
        self.assertFalse(profile["network_during_build"])

    def test_nul_paths_keep_whitespace(self):
        self.assertEqual(fields(b"v1\0base\0name\0/path with\nnewline;$\0/root\0", "v1"),
                         ["base", "name", "/path with\nnewline;$", "/root"])

    def test_unknown_unterminated_and_invalid_encoding(self):
        for data in [b"v2\0", b"v1", b"v1\0bad\xff\0"]:
            with self.assertRaises((AssertionError, UnicodeDecodeError)): fields(data, "v1")

    def test_dependency_triples_and_empty_graph(self):
        self.assertEqual(records(b"v1\0", "v1"), [])
        self.assertEqual(records(b"v1\0source\0name\0/path with\nnewline\0", "v1"),
                         [("source", "name", "/path with\nnewline")])

    def test_rejects_partial_unknown_duplicate_records(self):
        for data in [b"v1\0source\0name\0", b"v1\0unknown\0name\0path\0",
                     b"v1\0source\0name\0path\0source\0name\0path\0"]:
            with self.assertRaises(AssertionError): records(data, "v1")


if __name__ == "__main__": unittest.main()
