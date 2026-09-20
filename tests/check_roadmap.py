#!/usr/bin/env python3
"""Validate the public tracker, not the product's security/completion claims."""
import copy
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MILESTONES = {"M0", "M1a", "M1b", "M1c", "M1d", "M2a", "M2b", "M2c", "M2d",
              "M3a", "M3b", "M4", "M5", "M6", "M7", "M8", "M9", "M10"}
ACCEPTANCE = {"owner_registration", "git_upload_and_release", "verified_https_download",
              "luce_fresh_project", "luce_base_fresh_project", "locked_offline_relocated_build",
              "negative_security_and_restore"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(data):
    require(data["schema_version"] == 2, "unknown schema")
    require(data["origin"] == "https://pkg.luciaos.com", "canonical HTTPS origin changed")
    require(data["owner_handle"] == "dymokomi", "owner acceptance target changed")
    require(data["license"] == "MIT OR Apache-2.0", "license changed")
    require(data["client"] == {"repository": "luce-luc", "executable": "luc",
                              "compiler_commands": ["luce", "luce-base"],
                              "language_syntax_changes_required": False,
                              "luce_tooling_changes_required": True,
                              "package_document": "package.prisma",
                              "lock_document": "luc.lock",
                              "sandbox_command": "luce run --sandbox ROOT FILE -- ARGS",
                              "decision": "docs/CLI_DECISION.md"}, "standalone client contract changed")
    rows = data["milestones"] + data["final_acceptance"]
    by_id = {row["id"]: row for row in rows}
    require(len(by_id) == len(rows), "duplicate milestone")
    require({row["id"] for row in data["milestones"]} == MILESTONES, "missing/unknown milestone")
    require({row["id"] for row in data["final_acceptance"]} == ACCEPTANCE, "missing acceptance test")
    require(by_id["M7"]["repositories"] == ["luce-luc", "luce-pkg", "luce"] and
            by_id["M7"]["toolchains"] == ["luce", "luce-base"], "client implementation/toolchain boundary changed")
    require(by_id["M2d"]["repositories"] == ["luce"] and
            by_id["M2d"]["requires"] == ["M0"], "sandbox boundary changed")
    for identifier, language in [("luce_fresh_project", "luce"), ("luce_base_fresh_project", "luce-base")]:
        require(by_id[identifier].get("client") == "luc" and by_id[identifier].get("language") == language,
                "standalone client must exercise both languages")
    visited, active = set(), set()

    def visit(identifier):
        require(identifier in MILESTONES, "unknown prerequisite")
        require(identifier not in active, "dependency cycle")
        if identifier in visited:
            return
        active.add(identifier)
        for dependency in by_id[identifier]["requires"]:
            visit(dependency)
        active.remove(identifier)
        visited.add(identifier)

    for identifier in MILESTONES:
        visit(identifier)
    for row in rows:
        require(row["status"] in {"pending", "in_progress", "complete"}, "unknown status")
        require(len(row["requires"]) == len(set(row["requires"])), "duplicate prerequisite")
        for dependency in row["requires"]:
            require(dependency in MILESTONES, "unknown prerequisite")
        if row["id"] in ACCEPTANCE:
            require(row["requires"] == ["M10"], "production acceptance requires M10")
        if row["status"] == "complete":
            require(bool(row["evidence"]), "completion needs evidence")
            require(all(by_id[item]["status"] == "complete" for item in row["requires"]),
                    "incomplete prerequisite")
        for evidence in row["evidence"]:
            require(bool(re.fullmatch(r"[a-z][a-z0-9-]*", evidence["repository"])), "invalid repository")
            require(bool(re.fullmatch(r"[0-9a-f]{40}", evidence["commit"])), "pin exact commit")
            prefix = f'https://github.com/dymokomi/{evidence["repository"]}/actions/runs/'
            require(evidence["ci"].startswith(prefix) and evidence["ci"][len(prefix):].isdigit(), "invalid CI link")
            require(bool(evidence["scope"].strip()), "describe evidence scope and exclusions")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "roadmap.json").read_text())

    def test_current_tracker(self):
        validate(self.data)

    def test_refuses_missing_evidence(self):
        self.data["milestones"][0]["status"] = "complete"
        self.data["milestones"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate(self.data)

    def test_refuses_unfinished_dependency(self):
        self.data["milestones"][0]["status"] = "in_progress"
        self.data["milestones"][3]["status"] = "complete"
        with self.assertRaisesRegex(ValueError, "prerequisite"):
            validate(self.data)

    def test_cycles_and_unknown_dependencies(self):
        for dependency in ["M1a", "unknown"]:
            candidate = copy.deepcopy(self.data)
            candidate["milestones"][0]["requires"] = [dependency]
            with self.assertRaises(ValueError):
                validate(candidate)

    def test_missing_acceptance_and_duplicate(self):
        self.data["final_acceptance"].pop()
        with self.assertRaises(ValueError):
            validate(self.data)
        self.setUp()
        self.data["milestones"].append(self.data["milestones"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(self.data)

    def test_refuses_short_revision_and_foreign_evidence(self):
        evidence = self.data["milestones"][3]["evidence"][0]
        evidence["commit"] = "d13a1d1"
        with self.assertRaisesRegex(ValueError, "exact commit"):
            validate(self.data)
        self.setUp()
        self.data["milestones"][3]["evidence"][0]["ci"] = "https://example.com/1"
        with self.assertRaisesRegex(ValueError, "CI link"):
            validate(self.data)

    def test_refuses_embedded_cli_or_language_syntax_change(self):
        for field, value in [("executable", "luce"), ("language_syntax_changes_required", True)]:
            candidate = copy.deepcopy(self.data)
            candidate["client"][field] = value
            with self.assertRaisesRegex(ValueError, "standalone client"):
                validate(candidate)

    def test_both_languages_require_real_luc_acceptance(self):
        for identifier in ["luce_fresh_project", "luce_base_fresh_project"]:
            candidate = copy.deepcopy(self.data)
            row = next(item for item in candidate["final_acceptance"] if item["id"] == identifier)
            row["client"] = "mock"
            with self.assertRaisesRegex(ValueError, "both languages"):
                validate(candidate)


if __name__ == "__main__":
    unittest.main()
