"""The vendored derivation against Repository-Identicon's pinned vectors.

This repository is a delivery, not the standard. The half of
`console-colophon.py` above the Konsole banner is a copy, and a copy that is
not checked is a fork waiting to happen: the derivation drifts, a tab and a
README disagree about one project's colour, and nothing fails until a human
notices two different greens.

So `vectors.json` is committed here too and the copy is held to it. When the
vectors change upstream, copy them here and run this; if it fails, re-vendor
the derivation rather than editing it in place.

Standard library only, and no network.

    python3 -m unittest discover -s tests -t tests
"""

import importlib.util
import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "console-colophon.py"
VECTORS = ROOT / "vectors.json"

spec = importlib.util.spec_from_file_location("console_colophon", TOOL)
colophon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colophon)
vectors = json.loads(VECTORS.read_text())


class TestTheVendoredDerivationConforms(unittest.TestCase):
    """One test per property the specification fixes.

    A failure means this copy has moved away from the vectors, not that the
    vectors are wrong.
    """

    def test_there_are_vectors_to_check_against(self):
        self.assertTrue(vectors, "vectors.json is empty")

    def test_the_digest_matches(self):
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                self.assertEqual(vector["md5"], colophon._digest(vector["key"]))

    def test_the_grid_matches(self):
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                rows = ["".join("1" if cell else "0" for cell in row)
                        for row in colophon.identicon_grid(vector["key"])]
                self.assertEqual(vector["grid"], rows)

    def test_the_colour_matches(self):
        """Including the rounding rule. Half up, not half to even -- the one
        place a reimplementation in another language silently diverges."""
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                self.assertEqual(
                    vector["foreground"],
                    colophon.hex_colour(colophon.identicon_colour(vector["key"])))


class TestRemoteNormalisation(unittest.TestCase):
    """Every spelling of one repository must collapse to one key, or an SSH
    checkout and an HTTPS checkout of the same project get different marks."""

    EXPECTED = "github.com/owner/repo"
    SPELLINGS = (
        "https://github.com/Owner/Repo.git",
        "https://github.com/Owner/Repo",
        "https://github.com/owner/repo/",
        "https://token@github.com/Owner/Repo.git",
        "https://user:pass@github.com/Owner/Repo.git",
        "git@github.com:Owner/Repo.git",
        "git@github.com:Owner/Repo",
        "ssh://git@github.com/Owner/Repo.git",
        "ssh://git@github.com:2222/Owner/Repo.git",
        "git://github.com/Owner/Repo.git",
    )

    def test_every_spelling_in_the_specification_collapses_to_one_key(self):
        for url in self.SPELLINGS:
            with self.subTest(url=url):
                self.assertEqual(self.EXPECTED, colophon.normalise_remote_url(url))

    def test_a_local_path_remote_is_refused(self):
        for url in ("/srv/git/repo.git", "file:///srv/git/repo.git", "", None):
            with self.subTest(url=url):
                self.assertIsNone(colophon.normalise_remote_url(url))

    def test_the_host_is_kept_so_forges_stay_distinct(self):
        self.assertNotEqual(colophon.normalise_remote_url("git@github.com:a/b"),
                            colophon.normalise_remote_url("git@gitlab.com:a/b"))


class TestTheDerivedNames(unittest.TestCase):
    """The spec fixes the short id and the badge label; the prefix is ours."""

    def test_the_icon_name_is_the_prefix_and_the_twelve_character_short_id(self):
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                name = colophon.icon_name(vector["key"])
                self.assertTrue(name.startswith(f"{colophon.ICON_PREFIX}-"), name)
                self.assertEqual(12, len(name.rsplit("-", 1)[1]))

    def test_the_badge_label_is_at_most_two_upper_case_characters(self):
        """The vectors include the empty key on purpose, and it has no name to
        take a letter from, so an empty label is the correct answer there."""
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                label = colophon.badge_label(vector["key"])
                self.assertLessEqual(len(label), 2, label)
                self.assertEqual(label.upper(), label)
                if vector["key"]:
                    self.assertTrue(label, "a named project must get a label")


class TestTheRenderersProduceSomething(unittest.TestCase):

    def test_the_png_is_a_png(self):
        data = colophon.render_png("github.com/owner/repo", 64)
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])

    def test_the_svg_carries_one_rect_per_foreground_cell(self):
        """No background rect unless one is asked for -- the default is
        transparent, which is what makes the mark usable on any page."""
        key = "github.com/owner/repo"
        filled = sum(sum(1 for cell in row if cell)
                     for row in colophon.identicon_grid(key))
        self.assertEqual(filled, colophon.render_svg(key, 256).count("<rect"))
        self.assertEqual(filled + 1,
                         colophon.render_svg(key, 256, background=(0, 0, 0)).count("<rect"))


class TestNothingIsRemovedThatCannotBeFound(unittest.TestCase):
    """A prefix rename must not orphan icons the tool can no longer see.

    `uninstall` globs for the prefix, so renaming without sweeping the old
    names would leave files that only a human with `rm` could clear.
    """

    def test_the_legacy_prefixes_are_swept_too(self):
        self.assertIn(colophon.ICON_PREFIX, colophon.icon_prefixes())
        for legacy in colophon.LEGACY_ICON_PREFIXES:
            self.assertIn(legacy, colophon.icon_prefixes())

    def test_an_icon_installed_under_an_old_prefix_is_still_listed(self):
        import tempfile, shutil
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        apps = root / "48x48" / "apps"
        apps.mkdir(parents=True)
        for prefix in colophon.icon_prefixes():
            (apps / f"{prefix}-0123456789ab.png").write_bytes(b"")
        found = colophon.installed_icons(root)
        self.assertEqual(len(colophon.icon_prefixes()), len(found), found)


class TestTheCommandLine(unittest.TestCase):

    def test_it_reports_its_subcommands(self):
        done = subprocess.run(["python3", str(TOOL), "--help"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        for command in ("install", "list", "uninstall", "sessions", "probe",
                        "badge", "profile", "demo", "doctor"):
            self.assertIn(command, done.stdout)

    def test_doctor_runs_without_a_bus(self):
        """It must survive a machine with no Konsole and no session bus, or it
        is useless in exactly the situation someone runs it."""
        done = subprocess.run(["python3", str(TOOL), "doctor"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("icon prefix", done.stdout)


if __name__ == "__main__":
    unittest.main()
