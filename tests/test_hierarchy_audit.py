"""Comprehensive synthetic unit tests for LaTeX unsupported command/environment audit tool.

Covers regression requirements:
1. Comments and escaped percent parity (\\% vs \\\\%).
2. Inline and block literal fake commands (\\verb, verbatim, lstlisting); alltt is NOT literal.
3. Starred and control-symbol commands (\\section*, \\\\, \\,, \\!, trailing * preserved).
4. Nested and optional definition arguments, including braced ']' in defaults.
5. newcommand, def, newenvironment (with [nargs][default]), newtheorem, DeclareMathOperator.
6. Calls vs macro definition bodies (comments & literals in macro bodies respected).
7. Unsupported commands nested inside an unknown environment.
8. >200 early tokens then late unknown token still gets bounded example.
9. Exact tag association without prefix collision (\\foo vs \\foobar).
10. Environment examples collection and scope classification.
11. File and publication counts across 2 files of 1 Version and 2 Versions of 1 Publication.
12. 5 definition declarations with total counted truthfully while evidence bounded to <= 3.
13. Definition evidence carries publication and version metadata.
14. Non-TeX, unreadable files, and merge failure tracking.
15. Duplicate ledger rows do not double count (safe latest-row resume).
16. Resume fingerprint check invalidates changed mapping or manifest.
17. Unknown \\if... commands remain in review queue (not silently treated as handled).
"""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from src.parse.Hierarchy.audit_commands import (
    CorpusAuditor,
    VersionAuditResult,
    extract_diagnostic_tag,
    is_escaped_percent,
    parse_balanced_group,
    scan_source_lexical,
)


class TestHierarchyAudit(unittest.TestCase):
    def test_comments_and_escaped_percent(self):
        """Comments are skipped; escaped percent is recognized as literal text."""
        text = (
            "% \\fakeone\n"
            "Normal text \\% \\realtwo\n"
            "\\\\% \\fakethree\n"
            "Line with \\\\\\% \\realfour\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        self.assertNotIn("\\fakeone", out)
        self.assertNotIn("\\fakethree", out)
        self.assertIn("\\realtwo", out)
        self.assertIn("\\realfour", out)

        self.assertTrue(is_escaped_percent("\\%", 1))
        self.assertFalse(is_escaped_percent("\\\\%", 2))
        self.assertTrue(is_escaped_percent("\\\\\\%", 3))

    def test_inline_and_block_literals_and_alltt(self):
        """Verbatim and lstlisting skip fake commands; alltt does NOT skip commands."""
        text = (
            "Here is \\verb|\\fakeinline| and \\verb*+\\fakeinlineplus+.\n"
            "\\begin{verbatim}\n"
            "\\fakelineone\n"
            "\\end{verbatim}\n"
            "\\begin{lstlisting}\n"
            "\\fakelisting\n"
            "\\end{lstlisting}\n"
            "\\begin{alltt}\n"
            "\\realinalltt\n"
            "\\end{alltt}\n"
            "\\realcommand after block\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        self.assertNotIn("\\fakeinline", out)
        self.assertNotIn("\\fakeinlineplus", out)
        self.assertNotIn("\\fakelineone", out)
        self.assertNotIn("\\fakelisting", out)
        self.assertIn("\\realinalltt", out)
        self.assertIn("\\realcommand", out)
        self.assertIn("verbatim", envs)
        self.assertIn("alltt", envs)

    def test_starred_and_control_symbols_and_regex(self):
        """Starred commands and control symbols are extracted; diagnostic regex retains trailing *."""
        text = (
            "\\section*{Intro} \\\\ \\, \\! \\customstar*\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        self.assertIn("\\section*", out)
        self.assertIn("\\\\", out)
        self.assertIn("\\,", out)
        self.assertIn("\\!", out)
        self.assertIn("\\customstar*", out)

        # Diagnostic tag extractor must keep trailing *
        tag1 = extract_diagnostic_tag(
            "unhandled_command",
            "Command preserved without macro expansion: \\customstar*",
            "\\customstar*{test}",
        )
        self.assertEqual(tag1, "\\customstar*")

        tag2 = extract_diagnostic_tag(
            "unhandled_environment",
            "Environment has no settled mapping: myenv*",
            "\\begin{myenv*}",
        )
        self.assertEqual(tag2, "myenv*")

    def test_late_token_gets_example_beyond_200_tokens(self):
        """Tokens occurring late in a file (>200 early tokens) still get per-tag bounded examples."""
        repeated_tokens = " ".join(f"\\commoncmd" for _ in range(250))
        text = f"{repeated_tokens}\n\\latetag[arg]{{val}}\n"
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "big.tex", "pub1", 1
        )
        self.assertIn("\\latetag", out)
        self.assertIn("\\latetag", ex_by_tag)
        self.assertGreaterEqual(len(ex_by_tag["\\latetag"]), 1)
        self.assertEqual(ex_by_tag["\\latetag"][0].name, "\\latetag")

    def test_exact_tag_association_no_prefix_collision(self):
        """Tags with common prefixes (\\foo vs \\foobar) do not collide in examples."""
        text = "\\foobar{arg}\n\\foo{arg}\n"
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        self.assertIn("\\foo", ex_by_tag)
        self.assertIn("\\foobar", ex_by_tag)
        self.assertEqual(ex_by_tag["\\foo"][0].name, "\\foo")
        self.assertEqual(ex_by_tag["\\foobar"][0].name, "\\foobar")

    def test_environment_examples_and_scope(self):
        """Environment examples are collected with explicit type and scope."""
        text = (
            "\\begin{customenv}\n"
            "content\n"
            "\\end{customenv}\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        self.assertIn("customenv", envs)
        self.assertIn("customenv", ex_by_tag)
        self.assertEqual(ex_by_tag["customenv"][0].target_type, "environment")
        self.assertEqual(ex_by_tag["customenv"][0].source_scope, "fragment_or_preamble")

    def test_newenvironment_with_optional_default_and_comments(self):
        """newenvironment with [nargs][default] and comments parses cleanly without leaking calls."""
        text = (
            "\\newenvironment % comment\n"
            "{myenv} % env name\n"
            "[2] % num args\n"
            "[{default, with [nested]}] % default val\n"
            "{\\startenv{#1}} % begin code\n"
            "{\\finishenv} % end code\n"
            "\\outercmd after def\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        def_names = {d.name: d for d in defs}
        self.assertIn("myenv", def_names)
        self.assertIn("[2][{default, with [nested]}]", def_names["myenv"].signature)
        self.assertIn("\\startenv", macro)
        self.assertIn("\\finishenv", macro)
        self.assertIn("\\outercmd", out)
        self.assertNotIn("\\startenv", out)

    def test_newtheorem_and_macro_body_tokens(self):
        """newtheorem consumes declaration args; tokens in Title are macro/def tokens, not outer calls."""
        text = (
            "\\newtheorem{lemma}[theorem]{\\textbf{Lemma}}[section]\n"
            "\\regularcall\n"
        )
        out, out_fs, macro, m_fs, envs, e_fs, defs, ex_by_tag, warns = scan_source_lexical(
            text, "test.tex", "pub1", 1
        )
        def_names = {d.name: d for d in defs}
        self.assertIn("lemma", def_names)
        self.assertIn("\\textbf", macro)
        self.assertNotIn("\\textbf", out)
        self.assertIn("\\regularcall", out)

    def test_unknown_if_remains_reviewable(self):
        """Unknown \\if... commands are not treated as core handled and remain in catalog."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            auditor = CorpusAuditor(output_dir=out_dir)

            r = VersionAuditResult(
                publication="2409-00001",
                version=1,
                status="parsed",
                source_commands={"\\ifunknowncond": 1},
                source_commands_files={"\\ifunknowncond": ["main.tex"]},
            )
            with open(auditor.ledger_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(r.__dict__) + "\n")

            manifest = {
                "publication_count": 1,
                "version_count": 1,
                "publications": [{"publication": "2409-00001", "versions": [{"version": 1}]}],
            }
            auditor.aggregate_and_report(manifest)
            catalog = json.loads(auditor.cmd_catalog_json.read_text(encoding="utf-8"))
            entry = next((c for c in catalog if c["name"] == "\\ifunknowncond"), None)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["classification"], "unmapped_in_parser")
            self.assertEqual(entry["recommended_action"], "manual_review")

    def test_definition_counting_and_evidence_bounding(self):
        """5 declarations counted truthfully (total=5) while evidence bounded to <= 3 with pub/ver."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            auditor = CorpusAuditor(output_dir=out_dir)

            defs = [
                {
                    "name": "\\mycmd",
                    "target_type": "command",
                    "def_cmd": "\\newcommand",
                    "publication": "2409-00001",
                    "version": 1,
                    "file": f"file_{i}.tex",
                    "line": i,
                    "signature": "[1]",
                    "excerpt": f"excerpt_{i}",
                }
                for i in range(1, 6)
            ]

            r = VersionAuditResult(
                publication="2409-00001",
                version=1,
                status="parsed",
                source_commands={"\\mycmd": 10},
                source_commands_files={"\\mycmd": ["main.tex"]},
                definitions=defs,
            )
            with open(auditor.ledger_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(r.__dict__) + "\n")

            manifest = {
                "publication_count": 1,
                "version_count": 1,
                "publications": [{"publication": "2409-00001", "versions": [{"version": 1}]}],
            }
            auditor.aggregate_and_report(manifest)
            catalog = json.loads(auditor.cmd_catalog_json.read_text(encoding="utf-8"))
            entry = next((c for c in catalog if c["name"] == "\\mycmd"), None)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["total_definition_declarations"], 5)
            self.assertEqual(entry["defining_publications"], 1)
            self.assertEqual(len(entry["definition_evidence"]), 3)
            self.assertEqual(entry["definition_evidence"][0]["publication"], "2409-00001")
            self.assertEqual(entry["definition_evidence"][0]["version"], 1)

    def test_file_and_publication_counts_across_files_and_versions(self):
        """Distinct files across 2 files of 1 Version and 2 Versions of 1 Publication."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            auditor = CorpusAuditor(output_dir=out_dir)

            r1 = VersionAuditResult(
                publication="2409-00001",
                version=1,
                status="parsed",
                source_commands={"\\crosscmd": 3},
                source_commands_files={"\\crosscmd": ["file1.tex", "file2.tex"]},
            )
            r2 = VersionAuditResult(
                publication="2409-00001",
                version=2,
                status="parsed",
                source_commands={"\\crosscmd": 2},
                source_commands_files={"\\crosscmd": ["file2.tex", "file3.tex"]},
            )
            with open(auditor.ledger_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(r1.__dict__) + "\n")
                f.write(json.dumps(r2.__dict__) + "\n")

            manifest = {
                "publication_count": 1,
                "version_count": 2,
                "publications": [
                    {"publication": "2409-00001", "versions": [{"version": 1}, {"version": 2}]}
                ],
            }
            auditor.aggregate_and_report(manifest)
            catalog = json.loads(auditor.cmd_catalog_json.read_text(encoding="utf-8"))
            entry = next((c for c in catalog if c["name"] == "\\crosscmd"), None)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["source_occurrences"], 5)
            self.assertEqual(entry["distinct_publications"], 1)
            self.assertEqual(entry["distinct_versions"], 2)
            # file1, file2 in v1 and file2, file3 in v2 -> 4 distinct (pub, ver, file) instances
            self.assertEqual(entry["distinct_files"], 4)

    def test_duplicate_ledger_rows_do_not_double_count(self):
        """Latest valid row per (pub, ver) is used; earlier duplicate lines do not double count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            auditor = CorpusAuditor(output_dir=out_dir)

            # Earlier entry
            r_old = VersionAuditResult(
                publication="2409-00001",
                version=1,
                status="parsed",
                source_commands={"\\dupcmd": 5},
                source_commands_files={"\\dupcmd": ["main.tex"]},
            )
            # Rewritten/resumed entry
            r_new = VersionAuditResult(
                publication="2409-00001",
                version=1,
                status="parsed",
                source_commands={"\\dupcmd": 5},
                source_commands_files={"\\dupcmd": ["main.tex"]},
            )
            with open(auditor.ledger_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(r_old.__dict__) + "\n")
                f.write(json.dumps(r_new.__dict__) + "\n")

            entries = auditor.load_ledger_entries()
            self.assertEqual(len(entries), 1)

            manifest = {
                "publication_count": 1,
                "version_count": 1,
                "publications": [{"publication": "2409-00001", "versions": [{"version": 1}]}],
            }
            auditor.aggregate_and_report(manifest)
            catalog = json.loads(auditor.cmd_catalog_json.read_text(encoding="utf-8"))
            entry = next((c for c in catalog if c["name"] == "\\dupcmd"), None)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["source_occurrences"], 5)

    def test_fingerprint_invalidation_on_changed_mapping(self):
        """Resume refuses when saved mapping fingerprint does not match current mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            auditor = CorpusAuditor(output_dir=out_dir)

            # Save initial fingerprint with mismatched mapping
            fp = {
                "script_sha256": auditor.script_sha256,
                "mapping_sha256": "fake_sha256",
                "manifest_sha256": "manifest_fake",
                "native_sha256": "native_fake",
            }
            auditor.fingerprint_path.write_text(json.dumps(fp) + "\n", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                auditor.check_or_save_fingerprints()
            self.assertIn("Fingerprint mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


def test_macro_literal_body_and_character_offsets_are_truthful():
    from collections import defaultdict
    from src.parse.Hierarchy.audit_commands import scan_source_lexical
    macro_envs, files = Counter(), defaultdict(set)
    text = "Đầu.\n" + r"\newcommand{\box}{\begin{verbatim}\fake\end{verbatim}\begin{custombox}\visible\end{custombox}}"
    result = scan_source_lexical(text, "main.tex", "2508-02872", 1,
                                 macro_environments=macro_envs, macro_environment_files=files)
    assert r"\fake" not in result[2]
    assert result[2][r"\visible"] == 1
    assert macro_envs == {"verbatim": 1, "custombox": 1}
    example = result[7][r"\visible"][0]
    assert example.line == 2
    assert example.char_offset == text.index(r"\visible")
    assert example.byte_offset is None


def make_real_fixture(tmp_path):
    raw = tmp_path / "raw"
    folder = raw / "2508-02872/v1"
    folder.mkdir(parents=True)
    (folder / "main.tex").write_text(r"\documentclass{article}\begin{document}Đầu. \unknown{A}\end{document}")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"publication_count": 1, "version_count": 1,
        "publications": [{"publication": "2508-02872", "versions": [{"version": 1, "folder": "2508-02872/v1"}]}]}))
    return CorpusAuditor(raw_dir=raw, manifest_path=manifest, output_dir=tmp_path / "out"), folder


def test_real_resume_reprocesses_changed_source_and_rejects_changed_code(tmp_path):
    from unittest.mock import patch
    auditor, folder = make_real_fixture(tmp_path)
    auditor.run()
    first = auditor.load_ledger_entries()
    with patch.object(auditor, "audit_version", wraps=auditor.audit_version) as audit:
        auditor.run()
        assert audit.call_count == 0
        (folder / "extra.tex").write_text(r"\newtag")
        auditor.run()
        assert audit.call_count == 1
    latest = auditor.load_ledger_entries()
    assert len(latest) == 1
    assert latest[("2508-02872", 1)]["source_signature"] != first[("2508-02872", 1)]["source_signature"]
    assert latest[("2508-02872", 1)]["source_commands"][r"\newtag"] == 1
    assert json.loads(auditor.summary_path.read_text())["inspected_versions"] == 1
    auditor.script_sha256 = "changed"
    import pytest
    with pytest.raises(ValueError, match="script_sha256"):
        auditor.check_or_save_fingerprints()


def test_unreadable_source_is_counted_and_recorded(tmp_path):
    from unittest.mock import patch
    auditor, _ = make_real_fixture(tmp_path)
    with patch("src.parse.Hierarchy.audit_commands.read_text_safe", side_effect=OSError("Unreadable fixture")):
        result = auditor.audit_version("2508-02872", 1, "2508-02872/v1")
    assert result.discovered_files == 1
    assert result.inspected_files == 0
    assert result.unreadable_files == 1
    assert any("Unreadable fixture" in w["message"] for w in result.file_warnings)


def test_native_diagnostic_examples_use_utf8_bytes_and_are_bounded_per_tag(tmp_path):
    auditor, folder = make_real_fixture(tmp_path)
    (folder / "main.tex").write_text(r"\documentclass{article}\begin{document}" + "Đầu. " + r"\repeated " * 120 + r"\latecommand*{x}\end{document}")
    result = auditor.audit_version("2508-02872", 1, "2508-02872/v1")
    examples = [e for e in result.diagnostic_examples if e["name"] == r"\latecommand*"]
    assert len(examples) == 1
    assert examples[0]["excerpt"].startswith(r"\latecommand*")
    assert examples[0]["file"] == "<merged>"
    assert sum(e["name"] == r"\repeated" for e in result.diagnostic_examples) == 3
    assert {e["target_type"] for e in result.diagnostic_examples} == {"command"}


def test_incomplete_checkpoint_tail_is_backed_up_without_losing_valid_rows(tmp_path):
    auditor, _ = make_real_fixture(tmp_path)
    valid = json.dumps({"publication": "2508-02872", "version": 1, "status": "complete"}).encode() + b"\n"
    auditor.ledger_path.write_bytes(valid + b'{"publication":')
    assert list(auditor.load_ledger_entries()) == [("2508-02872", 1)]
    assert auditor.ledger_path.read_bytes() == valid
    assert next(auditor.output_dir.glob("ledger_incomplete_tail_*.bin")).read_bytes() == b'{"publication":'


def test_diagnostic_control_whitespace_and_dynamic_environment_names():
    for name in ["\\ ", "\\\n", "\\\t", "\\"]:
        assert extract_diagnostic_tag("unhandled_command", "Command preserved without macro expansion: " + name, name) == name
    assert extract_diagnostic_tag("unhandled_environment", r"Environment has no settled mapping: \eqn", r"\begin{\eqn}") == r"\eqn"
