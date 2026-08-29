"""The vendored derivation against the pinned vectors, and the desktop half
against a temporary XDG root.

This repository carries a **copy** of Repository-Identicon's derivation rather
than importing it. The copy is only worth anything if something proves it still
agrees, so that is what this suite is for: every vector in `vectors.json` must
reproduce exactly, and a vector nothing can draw must not be in the file.

Nothing here writes outside a temporary directory, and nothing reaches the
network. `git` must be on PATH -- the key-resolution tests run against real
repositories.

    python3 -m unittest discover -s tests -t tests
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
VECTORS = ROOT / "vectors.json"


def load(name, module):
    """Import a script by path -- the file is hyphen-named, so `import` cannot."""
    spec = importlib.util.spec_from_file_location(module, ROOT / name)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


cc = load("console-colophon.py", "console_colophon")
vectors = json.loads(VECTORS.read_text())["vectors"]


def a_repo(directory, remote=None):
    """A real git repository at `directory`, optionally with an origin."""
    subprocess.run(["git", "init", "-q", str(directory)], check=True,
                   capture_output=True)
    if remote:
        subprocess.run(["git", "-C", str(directory), "remote", "add", "origin", remote],
                       check=True, capture_output=True)


# ---- The vectors: the whole reason a vendored copy is allowed ----

class TestTheVendoredDerivation(unittest.TestCase):
    """If any of these fail, this copy has drifted and is no longer conforming."""

    def test_there_are_vectors_to_check_against(self):
        self.assertTrue(vectors, "vectors.json is empty")

    def test_only_the_version_this_copy_draws_is_pinned(self):
        covered = {cc.parse_key(v["key"])[0] for v in vectors}
        self.assertEqual({cc.MAPPING_VERSION}, covered)

    def test_every_digest_matches(self):
        for vector in vectors:
            with self.subTest(vector["key"]):
                self.assertEqual(vector["md5"], cc._digest(vector["key"]))

    def test_every_grid_matches(self):
        for vector in vectors:
            with self.subTest(vector["key"]):
                drawn = ["".join("1" if cell else "0" for cell in row)
                         for row in cc.identicon_grid(vector["key"])]
                self.assertEqual(vector["grid"], drawn)

    def test_every_colour_matches(self):
        for vector in vectors:
            with self.subTest(vector["key"]):
                self.assertEqual(vector["foreground"].lower(),
                                 cc.hex_colour(cc.identicon_colour(vector["key"])))

    def test_a_key_at_another_mapping_version_is_refused(self):
        with self.assertRaises(cc.UnknownMappingVersion):
            cc.identicon_colour("1:github.com/owner/repo")

    def test_derive_prints_what_validate_expects(self):
        """`repository-identicon validate -- console-colophon derive` must work."""
        for vector in vectors[:3]:
            completed = subprocess.run(
                ["python3", str(ROOT / "console-colophon.py"), "derive", vector["key"]],
                capture_output=True, text=True, check=True)
            got = json.loads(completed.stdout)
            self.assertEqual(vector["grid"], got["grid"])
            self.assertEqual(vector["foreground"].lower(), got["colour"].lower())


# ---- Resolving a key, which decides which mark gets installed ----

class TestResolvingAKey(unittest.TestCase):

    def test_a_remote_beats_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_repo(tmp, "git@github.com:Owner/Repo.git")
            seed, source = cc.resolve_seed(tmp)
            self.assertEqual(("github.com/owner/repo", "remote"), (seed, source))

    def test_a_committed_override_beats_the_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_repo(tmp, "git@github.com:Owner/Repo.git")
            (pathlib.Path(tmp) / cc.OVERRIDE_FILENAME).write_text(
                "# pinned\ngithub.com/someone/else\n")
            seed, source = cc.resolve_seed(tmp)
            self.assertEqual(("github.com/someone/else", "override"), (seed, source))

    def test_a_recorded_key_beats_every_derivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            a_repo(tmp, "git@github.com:Owner/Repo.git")
            recorded = "3:github.com/recorded/elsewhere"
            path = cc.key_path(tmp)
            path.parent.mkdir(parents=True)
            path.write_text(f"# a comment\n{recorded}\n")
            self.assertEqual((recorded, "key"), cc.resolve_key_for(tmp))

    def test_ssh_and_https_spellings_agree(self):
        self.assertEqual(cc.normalise_remote_url("git@github.com:Owner/Repo.git"),
                         cc.normalise_remote_url("https://github.com/Owner/Repo"))

    def test_a_local_path_remote_is_not_a_seed(self):
        self.assertIsNone(cc.normalise_remote_url("/srv/git/thing.git"))


# ---- The desktop half, against a temporary XDG root ----

class TestTheIconTheme(unittest.TestCase):

    KEY = "3:github.com/owner/repo"

    def test_install_writes_one_file_per_size_plus_a_scalable(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = cc.install_icon(self.KEY, root=tmp)
            self.assertEqual(len(cc.INSTALL_SIZES) + 1, len(written))
            for path in written:
                self.assertTrue(path.is_file(), path)

    def test_every_installed_png_is_exactly_the_size_it_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc.install_icon(self.KEY, root=tmp)
            for size in cc.INSTALL_SIZES:
                path = (pathlib.Path(tmp) / f"{size}x{size}" / "apps"
                        / f"{cc.icon_name(self.KEY)}.png")
                header = path.read_bytes()[16:24]
                self.assertEqual((size, size),
                                 (int.from_bytes(header[:4], "big"),
                                  int.from_bytes(header[4:], "big")))

    def test_listing_finds_what_install_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc.install_icon(self.KEY, root=tmp)
            self.assertIn(cc.icon_name(self.KEY), cc.installed_icons(tmp))

    def test_removing_takes_all_of_it_back_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            cc.install_icon(self.KEY, root=tmp)
            removed = cc.remove_icon(cc.icon_name(self.KEY), tmp)
            self.assertEqual(len(cc.INSTALL_SIZES) + 1, len(removed))
            self.assertEqual({}, cc.installed_icons(tmp))

    def test_the_prefix_is_this_tool_s_own(self):
        """SPEC.md fixes the short id and leaves the prefix to the tool."""
        self.assertTrue(cc.icon_name(self.KEY).startswith("console-colophon-"))
        self.assertIn(cc.short_hash(self.KEY), cc.icon_name(self.KEY))


class TestTheKonsoleProfile(unittest.TestCase):

    KEY = "3:github.com/owner/repo"

    def test_the_profile_sets_the_icon_and_nothing_else(self):
        body = cc.profile_body(self.KEY)
        self.assertEqual(["[General]", "Name=", "Parent=", "Icon="],
                         [line.split("=")[0] + ("=" if "=" in line else "")
                          for line in body.strip().splitlines()])

    def test_the_icon_line_is_a_theme_name_and_not_a_path(self):
        icon = [l for l in cc.profile_body(self.KEY).splitlines()
                if l.startswith("Icon=")][0]
        self.assertNotIn("/", icon)

    def test_installing_writes_one_profile_the_listing_then_finds(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = cc.install_profile(self.KEY, directory=tmp)
            self.assertTrue(target.is_file())
            self.assertEqual([target], cc.installed_profiles(tmp))

    def test_the_display_name_carries_the_discriminator(self):
        self.assertIn(cc.short_hash(self.KEY, 6), cc.profile_name(self.KEY))


class TestTheBus(unittest.TestCase):

    def test_a_bad_session_spec_is_refused_rather_than_guessed(self):
        with self.assertRaises(cc.DBusError):
            cc.resolve_session("not-a-spec")

    def test_the_environment_decides_when_it_is_set(self):
        with mock.patch.dict(os.environ, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole-1",
                                          "KONSOLE_DBUS_SESSION": "/Sessions/2"}):
            self.assertEqual(("org.kde.konsole-1", "/Sessions/2"),
                             cc.resolve_session())

    def test_a_failing_command_raises_rather_than_returning_junk(self):
        with self.assertRaises(cc.DBusError):
            cc._run(["false"])


# ---- Nothing here may write outside a temporary directory ----

class TestScope(unittest.TestCase):

    def test_the_theme_root_follows_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                self.assertEqual(pathlib.Path(tmp) / "icons" / "hicolor",
                                 cc.icon_theme_root())
                self.assertEqual(pathlib.Path(tmp) / "konsole",
                                 cc.konsole_profile_dir())

    def test_this_repository_defines_no_artifact_writer(self):
        """`apply` and the `.identicon/` files belong to Repository-Identicon.

        The terminal renderings used to be on this list and are not any more:
        `emit` and everything under it came here, because where bytes land on a
        terminal is a decision about somebody's terminal. Writing files into
        somebody's repository is still not this tool's business.
        """
        for gone in ("install_into_repo", "artifact_bytes", "readme_state",
                     "artifact_names", "artifact_paths"):
            self.assertFalse(hasattr(cc, gone), f"{gone} should not be here")

    def test_the_terminal_renderings_arrived_whole(self):
        """Half a move is worse than none: a style naming a routine that did
        not come across fails only when somebody asks for that style."""
        for name in ("render", "render_inline", "render_text", "render_banner",
                     "render_line", "render_ansi", "iterm2_image", "kitty_image",
                     "resolve_protocol", "resolve_colour_depth", "cmd_emit"):
            self.assertTrue(hasattr(cc, name), f"{name} did not come across")
        self.assertEqual(("icon", "image", "text", "full", "banner", "line"),
                         cc.STYLES)


# ---- The terminal renderings ----

class TestTheTerminalRenderings(unittest.TestCase):
    """SPEC.md §§ Renderings, Terminal and Text define these; this is where they
    are implemented. `vectors.json` pins the grid and the colour, so what is
    left to check is that every style produces something on every vector, and
    that the styles keep the shapes their media depend on."""

    def test_every_style_renders_every_vector(self):
        for vector in vectors:
            for style in cc.STYLES:
                with self.subTest(key=vector["key"], style=style):
                    out = cc.render(vector["key"], style=style,
                                    protocol=cc.ITERM2, depth=cc.TRUECOLOR)
                    self.assertTrue(out.endswith("\n"), style)
                    self.assertTrue(out.strip(), f"{style} rendered nothing")

    def test_the_line_style_is_one_line_at_every_depth(self):
        """It exists for a medium that affords exactly one, so a second line
        would not be degraded output -- it would be broken output. At depth
        `none` this once raised TypeError instead."""
        for vector in vectors:
            for depth in cc.COLOUR_DEPTHS:
                with self.subTest(key=vector["key"], depth=depth):
                    out = cc.render(vector["key"], style="line", depth=depth)
                    self.assertEqual(1, out.count("\n"), repr(out))

    def test_the_text_style_carries_no_escape_sequence(self):
        """SPEC.md: escape-sequence colour is not part of this rendering. The
        colour rides in the emoji squares, which is what makes it survive a
        channel that strips ANSI."""
        for vector in vectors:
            with self.subTest(key=vector["key"]):
                out = cc.render(vector["key"], style="text", depth=cc.TRUECOLOR)
                self.assertNotIn("\033", out)

    def test_icon_falls_back_to_text_where_nothing_carries_an_image(self):
        key = vectors[0]["key"]
        self.assertEqual(cc.render(key, style="text", protocol=cc.TEXT),
                         cc.render(key, style="icon", protocol=cc.TEXT))

    def test_the_inline_image_declares_the_pngs_own_byte_count(self):
        """`size` is the payload length, and the PNG's pixel size is what
        decides how large it lands: Konsole ignores the protocol's width and
        height arguments."""
        key = vectors[0]["key"]
        for size in (40, 64):
            with self.subTest(size=size):
                png = cc.render_png(key, cc.fit_block(size), edge=size)
                self.assertIn(f"size={len(png)}",
                              cc.render_inline(key, cc.ITERM2, size))

    def test_the_sibling_text_module_is_named_when_it_is_missing(self):
        """`emit`'s text styles need it, and a missing sibling must say which
        file rather than raising something about importlib."""
        with tempfile.TemporaryDirectory() as tmp:
            alone = pathlib.Path(tmp) / "console-colophon.py"
            alone.write_bytes((ROOT / "console-colophon.py").read_bytes())
            done = subprocess.run(
                ["python3", str(alone), "emit", "--style", "text", str(ROOT)],
                capture_output=True, text=True, timeout=60)
            self.assertNotEqual(0, done.returncode)
            self.assertIn("text-identicon.py", done.stderr)


if __name__ == "__main__":
    unittest.main()
