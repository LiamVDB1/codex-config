from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from git_provenance import ProvenanceError, collect_git_provenance, normalize_remote  # noqa: E402

CANONICAL = "https://github.com/LiamVDB1/codex-config.git"
SUBDIR = "platform-repository"


class GitProvenanceTests(unittest.TestCase):
    def _commit(self, repo: Path, filename: str, content: str) -> None:
        target = repo / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self.git("-C", str(repo), "add", ".")
        self.git("-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", filename)

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=60
        )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        seed = base / "seed"
        seed.mkdir()
        self.git("init", "-q", "-b", "main", str(seed))
        self._commit(seed, SUBDIR + "/app.py", "print('v3')\n")
        self.git("-C", str(seed), "remote", "add", "origin", CANONICAL)
        bare = base / "origin.git"
        self.git("init", "-q", "--bare", str(bare))
        self.git("-C", str(seed), "push", "-q", str(bare), "main")
        self.clone = base / "clone"
        self.git("clone", "-q", str(bare), str(self.clone))
        self.git("-C", str(self.clone), "remote", "set-url", "origin", CANONICAL)
        self.seed = seed
        self.base = base

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_remote_spellings_normalize(self) -> None:
        self.assertEqual(
            normalize_remote("git@github.com:LiamVDB1/codex-config.git"),
            normalize_remote("https://github.com/LiamVDB1/codex-config.git"),
        )

    def test_measures_clean_clone_and_binds_subtree(self) -> None:
        receipt = collect_git_provenance(
            self.clone,
            expected_remote=CANONICAL,
            allowed_branches=["main"],
            source_subdir=SUBDIR,
            now="2026-08-26T00:00:00Z",
        )
        self.assertTrue(receipt["clean"])
        self.assertEqual(receipt["contained_branches"], ["main"])
        self.assertEqual(receipt["subdir_tree"], self.git("-C", str(self.seed), "rev-parse", f"HEAD:{SUBDIR}").stdout.strip())
        self.assertEqual(receipt["captured_at"], "2026-08-26T00:00:00Z")

    def test_dirty_tree_is_derived_not_asserted(self) -> None:
        (self.clone / "scratch.txt").write_text("dirty\n")
        receipt = collect_git_provenance(
            self.clone,
            expected_remote=CANONICAL,
            allowed_branches=["main"],
            source_subdir=SUBDIR,
        )
        self.assertIs(receipt["clean"], False)

    def test_wrong_remote_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProvenanceError, "canonical remote"):
            collect_git_provenance(
                self.clone,
                expected_remote="https://example.com/other.git",
                allowed_branches=["main"],
                source_subdir=SUBDIR,
            )

    def test_head_on_unknown_branch_is_rejected(self) -> None:
        self.git("-C", str(self.clone), "checkout", "-q", "-b", "feature/x")
        (self.clone / SUBDIR / "unreleased.txt").write_text("not pushed\n")
        self._commit(self.clone, SUBDIR + "/unreleased.txt", "not pushed\n")
        with self.assertRaisesRegex(ProvenanceError, "allowed remote branch"):
            collect_git_provenance(
                self.clone,
                expected_remote=CANONICAL,
                allowed_branches=["main"],
                source_subdir=SUBDIR,
            )

    def test_missing_subdir_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProvenanceError, "rev-parse"):
            collect_git_provenance(
                self.clone,
                expected_remote=CANONICAL,
                allowed_branches=["main"],
                source_subdir="does/not/exist",
            )


if __name__ == "__main__":
    unittest.main()
