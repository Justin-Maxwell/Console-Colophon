#!/usr/bin/env python3
"""Per-project identicons on the desktop: the XDG icon theme, and Konsole tabs.

A key -- `<mapping version>:host/owner/repo` -- becomes a 5x5 grid and one
colour. This tool puts that mark where a desktop can see it.

    icon theme   install, list, uninstall
    Konsole      profile, badge, probe, sessions, demo
    terminal     emit
    checking     derive, doctor

The derivation is **vendored** from the Repository-Identicon specification, not
imported. That is the intended shape: what holds implementations together is
`vectors.json`, checked by `tests/`, not a package. See README.md.

`text-identicon.py` must sit beside this file: `emit`'s text styles need its
sextant table and emoji palette.

Standard library only. Every subprocess is invoked with an argument list.
"""

import argparse
import base64
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import zlib

VERSION = "0.0.build"

# =============================================================================
# Vendored: the specification
#
# Everything between here and the next banner is a copy of the derivation
# defined by Repository-Identicon's SPEC.md, held to `vectors.json` by
# `tests/test_conformance.py`. **The reasoning lives in SPEC.md and is not
# repeated here**; a vendored copy that also carries the argument becomes a
# second, drifting specification. Change nothing in this section without a
# vector to prove the change.
# =============================================================================

MAPPING_VERSION = 3
KEY_STAMP = re.compile(r"^([0-9]+):(.*)$", re.DOTALL)

GRID = 5
BORDER = 1
ARTIFACT_BLOCK = 5

MARK_LIGHTNESS = 0.60
MARK_CHROMA = 0.26
HUE_WARP = (215.0, 50.0, 4.0)
GAMUT_STEPS = 30
GAMUT_CEILING = 0.4

OVERRIDE_FILENAME = ".repository-identicon"
LEGACY_OVERRIDE_FILENAMES = (".claude-state-identicon",)
IDENTICON_DIR = ".identicon"
KEY_NAME = "repository-identicon.key"


# ---- Resolving a key ----

def normalise_seed(path):
    """A filesystem path as a stable string: expanded, absolute, no trailing sep."""
    expanded = os.path.expanduser(str(path))
    absolute = os.path.abspath(expanded)
    return absolute.rstrip(os.sep) or os.sep


def normalise_remote_url(url):
    """A git remote URL as `host/owner/repo`, lowercased, or None for a local path."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    if not url or url.startswith("/") or url.startswith("file://"):
        return None

    if "://" in url:
        scheme, _, rest = url.partition("://")
        if scheme.lower() == "file":
            return None
        authority, _, path = rest.partition("/")
    elif ":" in url:
        authority, _, path = url.partition(":")     # scp-like: [user@]host:path
    else:
        return None

    if "@" in authority:
        authority = authority.rpartition("@")[2]
    host = authority.partition(":")[0]              # drop any port

    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[: -len(".git")]

    parts = [part for part in path.split("/") if part]
    if not host or not parts:
        return None
    return "/".join([host] + parts).lower()


def _git(args, cwd=None):
    """Stripped stdout of a git command, or None if it fails."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd if cwd else os.getcwd()), *args],
            capture_output=True, text=True
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def repo_toplevel(path):
    """The working tree root, or None outside a repository."""
    return _git(["rev-parse", "--show-toplevel"], path)


def repo_remote_url(path):
    """The origin URL, falling back to whichever remote is listed first."""
    url = _git(["remote", "get-url", "origin"], path)
    if url:
        return url
    remotes = _git(["remote"], path)
    if not remotes:
        return None
    return _git(["remote", "get-url", remotes.splitlines()[0].strip()], path)


def override_seed(directory):
    """The seed committed at `directory`, if there is a usable one."""
    if not directory:
        return None
    for name in (OVERRIDE_FILENAME, *LEGACY_OVERRIDE_FILENAMES):
        try:
            text = (pathlib.Path(directory) / name).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return None


def resolve_seed(path=None, explicit=None):
    """(seed, source): explicit, override, remote, toplevel or path."""
    directory = normalise_seed(path if path else os.getcwd())
    if explicit:
        return explicit, "explicit"

    toplevel = repo_toplevel(directory)

    committed = override_seed(toplevel or directory)
    if committed:
        return committed, "override"

    if toplevel:
        remote = normalise_remote_url(repo_remote_url(directory))
        if remote:
            return remote, "remote"
        return normalise_seed(toplevel), "toplevel"

    return directory, "path"


def stamp_key(seed, version=None):
    """`<version>:<seed>` -- what a freshly seeded repository records."""
    if version is None:
        version = MAPPING_VERSION
    return f"{version}:{seed}"


def parse_key(key):
    """(mapping_version, seed). An unstamped key is version 0 and its own seed."""
    match = KEY_STAMP.match(key)
    if not match:
        return 0, key
    return int(match.group(1)), match.group(2)


def key_path(root):
    """Where a seeded repository records its key."""
    return pathlib.Path(root) / IDENTICON_DIR / KEY_NAME


def recorded_key(root):
    """The recorded key, verbatim, or None if the repository is not seeded."""
    path = key_path(root)
    if not path.is_file():
        return None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def resolve_key_for(path=None, explicit=None):
    """(key, source): the recorded key if there is one, else today's derivation."""
    seed, source = resolve_seed(path, explicit)
    if not explicit:
        recorded = recorded_key(repo_toplevel(path) or (path or os.getcwd()))
        if recorded is not None:
            return recorded, "key"
    return stamp_key(seed), source


# ---- The grid and the colour ----

def _digest(key):
    """MD5 of the key as 32 lowercase hex characters."""
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def identicon_grid(key):
    """The 5x5 grid: digest characters 0-14, centre column out, mirrored."""
    digest = _digest(key)
    grid = [[False] * GRID for _ in range(GRID)]
    for index in range(15):
        painted = int(digest[index], 16) % 2 == 0
        column, row = divmod(index, GRID)
        grid[row][2 - column] = painted
        grid[row][2 + column] = painted
    return grid


def identicon_hue(key):
    """A fraction of a turn, from the last seven digest characters."""
    return int(_digest(key)[-7:], 16) / 0xFFFFFFF


def _quantise(value):
    """Round half up, not half to even."""
    return int(value * 255 + 0.5)


def _warp_bump(turned, half):
    """The integral of the raised-cosine bump, from its start to `turned`."""
    if turned <= -half:
        return 0.0
    if turned >= half:
        return half
    return (0.5 * (turned + half)
            + (half / (2 * math.pi)) * math.sin(math.pi * turned / half))


def warp_hue(degrees, warp=HUE_WARP):
    """A uniform draw in degrees to the hue it names. Monotonic, onto [0, 360)."""
    if warp is None:
        return degrees % 360.0
    centre, half, peak = warp
    degrees %= 360.0
    total = 360.0 + (peak - 1.0) * half
    return 360.0 * (degrees
                    + (peak - 1.0) * _warp_bump(degrees - centre, half)) / total


def _oklch_to_linear(lightness, chroma, degrees):
    """OkLCh to linear-light RGB, unclamped so the caller can test the range."""
    radians = math.radians(degrees)
    a = chroma * math.cos(radians)
    b = chroma * math.sin(radians)
    long_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * long_ - 3.3077115913 * medium + 0.2309699292 * short,
            -1.2684380046 * long_ + 2.6097574011 * medium - 0.3413193965 * short,
            -0.0041960863 * long_ - 0.7034186147 * medium + 1.7076147010 * short)


def _in_gamut(linear):
    return all(-1e-4 <= channel <= 1 + 1e-4 for channel in linear)


def gamut_chroma(degrees, lightness=MARK_LIGHTNESS, cap=MARK_CHROMA):
    """The chroma this hue gets: the cap, or the most sRGB allows."""
    if _in_gamut(_oklch_to_linear(lightness, cap, degrees)):
        return cap
    low, high = 0.0, GAMUT_CEILING
    for _ in range(GAMUT_STEPS):
        middle = (low + high) / 2
        if _in_gamut(_oklch_to_linear(lightness, middle, degrees)):
            low = middle
        else:
            high = middle
    return min(cap, int(low * 10000) / 10000)


def _encode(channel):
    """Linear light to an sRGB component, 0-255, rounded half up."""
    channel = max(0.0, min(1.0, channel))
    encoded = (1.055 * channel ** (1 / 2.4) - 0.055
               if channel > 0.0031308 else 12.92 * channel)
    return _quantise(encoded)


class UnknownMappingVersion(ValueError):
    """A key stamped at a version this build does not implement."""


def identicon_colour(key, chroma=MARK_CHROMA, lightness=MARK_LIGHTNESS):
    """The foreground colour as an (r, g, b) triple of 0-255 ints."""
    version, _ = parse_key(key)
    if version != MAPPING_VERSION:
        raise UnknownMappingVersion(
            f"key is stamped at mapping version {version}; this build "
            f"implements {MAPPING_VERSION} only. Use `repository-identicon "
            f"apply --remap` in that repository.")

    degrees = warp_hue(identicon_hue(key) * 360.0)
    return tuple(_encode(channel) for channel in
                 _oklch_to_linear(lightness, gamut_chroma(degrees, lightness,
                                                          chroma), degrees))


def _colour_for(key, kwargs):
    """`identicon_colour` with chroma and lightness taken from render kwargs."""
    return identicon_colour(key, kwargs.get("chroma", MARK_CHROMA),
                            kwargs.get("lightness", MARK_LIGHTNESS))


# ---- Names the specification fixes ----

def hex_colour(rgb):
    """An (r, g, b) triple as `#rrggbb`."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def short_hash(key, length=12):
    """The short id: the first `length` characters of sha256(key)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


def project_name(key):
    """The last segment of the key, or the whole key if it has no separator."""
    return os.path.basename(key) or key


def badge_label(key, limit=2):
    """One or two upper-case characters: initials, else leading characters."""
    name = project_name(key)
    flat = name
    for separator in ("_", ".", " "):
        flat = flat.replace(separator, "-")
    words = [part for part in flat.split("-") if part]
    if len(words) >= 2:
        return "".join(word[0] for word in words[:limit]).upper()
    return name[:limit].upper()


# ---- Geometry and rendering ----

def canvas_edge(block, border):
    """The square canvas a block and a border imply."""
    return GRID * block + 2 * border


def fit_block(edge, border=1):
    """The largest block that fits a canvas somebody else fixed."""
    block = (edge - 2 * border) // GRID
    if block < 1:
        block = max(1, edge // GRID)
    return block


def render_rgba(key, block, border=BORDER, chroma=MARK_CHROMA,
                lightness=MARK_LIGHTNESS, background=None, edge=None):
    """Raw RGBA bytes for a square identicon of `block`-pixel blocks."""
    grid = identicon_grid(key)
    red, green, blue = identicon_colour(key, chroma, lightness)
    if edge is None:
        edge, margin = canvas_edge(block, border), border
    else:
        margin = (edge - block * GRID) // 2

    if background is None:
        back = bytes((0, 0, 0, 0))
    else:
        back = bytes(tuple(background) + (255,))
    fore = bytes((red, green, blue, 255))

    rows = []
    for y in range(edge):
        row = bytearray()
        grid_y = (y - margin) // block if block else -1
        inside_y = margin <= y < margin + block * GRID
        for x in range(edge):
            grid_x = (x - margin) // block if block else -1
            inside_x = margin <= x < margin + block * GRID
            if inside_x and inside_y and grid[grid_y][grid_x]:
                row += fore
            else:
                row += back
        rows.append(bytes(row))
    return b"".join(rows)


def _png_chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(rgba, width, height):
    """Minimal 8-bit RGBA PNG encoder. Flat colour blocks compress to nothing."""
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def render_png(key, block, **kwargs):
    """A PNG of the identicon."""
    edge = kwargs.get("edge") or canvas_edge(block, kwargs.get("border", BORDER))
    return encode_png(render_rgba(key, block, **kwargs), edge, edge)


def render_svg(key, block=ARTIFACT_BLOCK, border=BORDER, chroma=MARK_CHROMA,
               lightness=MARK_LIGHTNESS, background=None):
    """An SVG of the identicon: one <rect> per foreground cell."""
    grid = identicon_grid(key)
    colour = hex_colour(identicon_colour(key, chroma, lightness))
    size = canvas_edge(block, border)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
    ]
    if background is not None:
        parts.append(f'<rect width="{size}" height="{size}" '
                     f'fill="{hex_colour(background)}"/>')
    for row in range(GRID):
        for column in range(GRID):
            if grid[row][column]:
                x = border + column * block
                y = border + row * block
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{block}" height="{block}" fill="{colour}"/>'
                )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_ansi(key):
    """Terminal preview: two spaces per cell on a background colour."""
    grid = identicon_grid(key)
    red, green, blue = identicon_colour(key)
    lines = []
    for row in grid:
        line = ""
        for filled in row:
            line += f"\033[48;2;{red};{green};{blue}m  \033[0m" if filled else "  "
        lines.append(line)
    return "\n".join(lines)


# =============================================================================
# This tool: putting a mark on a terminal
#
# SPEC.md §§ Renderings, Terminal and Text define these and rank them: inline
# image first, then a lattice with the tricolour, then the tricolour alone.
# What they do not decide is *where the bytes go*, and that is a decision about
# somebody's terminal rather than about the mark -- which is the Scope rule, so
# it lives here.
#
# The escape sequences are held to nothing but this file. `vectors.json` pins
# the grid and the colour, and those are checked in the vendored section above;
# an escape sequence is a wrapper around bytes that are already pinned.
# =============================================================================

# ---- Terminal colour ----

TRUECOLOR = "truecolor"
INDEXED = "256"
NONE = "none"
COLOUR_DEPTHS = (TRUECOLOR, INDEXED, NONE)


def resolve_colour_depth(requested=None, environ=None):
    """Pick a colour depth. NO_COLOR wins over everything, per no-color.org."""
    environ = os.environ if environ is None else environ
    if environ.get("NO_COLOR") is not None:
        return NONE
    if requested and requested != "auto":
        return requested
    if environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return TRUECOLOR
    return INDEXED


def _xterm256(rgb):
    """Nearest colour in the xterm 6x6x6 cube."""
    red, green, blue = (int(component * 5 / 255 + 0.5) for component in rgb)
    return 16 + 36 * red + 6 * green + blue


def _fg(rgb, depth):
    if depth == NONE:
        return ""
    if depth == TRUECOLOR:
        return "\033[38;2;{};{};{}m".format(*rgb)
    return f"\033[38;5;{_xterm256(rgb)}m"


RESET = "\033[0m"

CHIP = "█"

# The text rendering lives in text-identicon.py, which takes a grid and a colour
# and nothing else. Loaded by path because the file name carries a hyphen.
#
# **These two files are a pair and must be deployed together**: the sextant
# table and the emoji palette live next door. `doctor` reports whether the
# sibling is present.
TEXT_MODULE = "text-identicon.py"
_TEXT = None


def text_module_path():
    return pathlib.Path(__file__).with_name(TEXT_MODULE)


def _text_module():
    global _TEXT
    if _TEXT is None:
        import importlib.util
        path = text_module_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"{TEXT_MODULE} must sit beside {pathlib.Path(__file__).name}; "
                f"the text renderings need its sextant table")
        spec = importlib.util.spec_from_file_location("text_identicon", path)
        _TEXT = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TEXT)
    return _TEXT


def render_text(key, chroma=MARK_CHROMA, lightness=MARK_LIGHTNESS):
    """The identicon as two lines of three characters: the sextant grid, then
    the tricolour.

    One glyph covers six cells, so a cell is not separately addressable and the
    colour lives in the emoji squares rather than in an escape sequence.
    """
    grid = identicon_grid(key)
    colour = identicon_colour(key, chroma, lightness)
    return _text_module().text(grid, colour).split("\n")


def render_banner(key, source=None, depth=TRUECOLOR, **kwargs):
    """The identicon with the project name beside it."""
    rows = render_text(key, kwargs.get("chroma", MARK_CHROMA),
                       kwargs.get("lightness", MARK_LIGHTNESS))
    colour = _colour_for(key, kwargs)
    name = project_name(key)
    if depth != NONE:
        name = f"{_fg(colour, depth)}{name}{RESET}"
    labels = [name, key if source != "path" else ""]
    return [f"{row}  {label}".rstrip() for row, label in zip(rows, labels)]


def render_line(key, depth=TRUECOLOR, **kwargs):
    """One line: the colour, then the project name. For the tightest prompts.

    The grid cannot be one line -- five rows over either lattice is two text
    lines and no arrangement makes it one -- so anything that affords a single
    line loses the pattern and keeps only the colour. A coloured chip where
    escape sequences work, the tricolour where they do not.

    The tricolour takes the grid as well as the colour, because its order comes
    from the grid. Calling it with the colour alone raised `TypeError` on every
    `--colour none` run, which is the one path this branch exists to serve.
    """
    colour = _colour_for(key, kwargs)
    mark = (f"{_fg(colour, depth)}{CHIP}{RESET}" if depth != NONE
            else _text_module().tricolour(colour, identicon_grid(key)))
    return [f"{mark} {project_name(key)}"]


# ---- Inline images ----
#
# The blocks above are an approximation. Where the terminal can take a real
# image, send the PNG itself, base64 in an escape sequence.
#
# Konsole implements the iTerm2 file protocol: Vt102Emulation::osc_put matches
# the literal "1337;File=" and then waits for the ":" terminator, so arguments
# between the two are tolerated and ignored. It also handles kitty APC graphics
# and sixel.

ITERM2 = "iterm2"
KITTY = "kitty"
TEXT = "text"
PROTOCOLS = (ITERM2, KITTY, TEXT)

# Native pixel size for the inline image. Konsole ignores the protocol's own
# width and height arguments, so the PNG's own size is what decides how big it
# lands: five cells of eight pixels, about two text rows tall.
INLINE_SIZE = 40


def resolve_protocol(requested=None, environ=None):
    """Pick a graphics protocol from the environment.

    Detection is by environment variable rather than by querying the terminal,
    because something waiting on a terminal reply hangs when nothing answers.
    """
    environ = os.environ if environ is None else environ
    if requested and requested != "auto":
        return requested
    if environ.get("NO_COLOR") is not None:
        return TEXT
    if environ.get("KITTY_WINDOW_ID") or "kitty" in environ.get("TERM", "").lower():
        return KITTY
    if environ.get("KONSOLE_VERSION") or environ.get("KONSOLE_DBUS_SESSION"):
        return ITERM2
    if environ.get("TERM_PROGRAM", "") in ("iTerm.app", "WezTerm", "ghostty", "vscode"):
        return ITERM2
    return TEXT


def iterm2_image(png):
    """OSC 1337 File, the iTerm2 inline image protocol.

    No argument may contain a colon, since the colon is what terminates the
    argument list and begins the payload.
    """
    payload = base64.b64encode(png).decode("ascii")
    args = ";".join(["inline=1", f"size={len(png)}", "preserveAspectRatio=1"])
    return f"\033]1337;File={args}:{payload}\a"


def kitty_image(png, chunk_size=4096):
    """APC _G, the kitty graphics protocol. Chunked, as the protocol requires."""
    payload = base64.b64encode(png).decode("ascii")
    chunks = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)] or [""]
    out = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        control = f"a=T,f=100,m={more}" if index == 0 else f"m={more}"
        out.append(f"\033_G{control};{chunk}\033\\")
    return "".join(out)


def render_inline(key, protocol, size=INLINE_SIZE, **kwargs):
    """The identicon as a real image, or None if the protocol cannot carry one."""
    if protocol not in (ITERM2, KITTY):
        return None
    png = render_png(key, fit_block(size), edge=size, **kwargs)
    return iterm2_image(png) if protocol == ITERM2 else kitty_image(png)


# The lambdas normalise the signatures: `render` hands every style `source` and
# `depth`, and only `banner` wants both.
_TEXT_STYLES = {
    TEXT: lambda key, source=None, depth=TRUECOLOR, **kw: render_text(
        key, kw.get("chroma", MARK_CHROMA), kw.get("lightness", MARK_LIGHTNESS)),
    "full": lambda key, source=None, depth=TRUECOLOR, **kw: render_ansi(key).splitlines(),
    "banner": render_banner,
    "line": lambda key, source=None, depth=TRUECOLOR, **kw: render_line(key, depth, **kw),
}

STYLES = ("icon", "image", TEXT, "full", "banner", "line")


def render(key, style="icon", source=None, depth=TRUECOLOR, protocol=TEXT,
           size=INLINE_SIZE, **kwargs):
    """Return everything to write for one identicon, trailing newline included.

    The default is the icon and nothing else -- no project name, no key. The
    identicon is the message; anything beside it is the terminal's own business.
    """
    if style == "icon":
        inline = render_inline(key, protocol, size, **kwargs)
        if inline is not None:
            return inline + "\n"
        style = TEXT

    if style == "image":
        inline = render_inline(key, protocol if protocol != TEXT else ITERM2,
                               size, **kwargs)
        return (inline or "") + "\n"

    lines = _TEXT_STYLES[style](key, source=source, depth=depth, **kwargs)
    return "".join(line + "\n" for line in lines)


# =============================================================================
# This tool: the desktop
#
# Everything below is a side effect -- a file under ~/.local/share, or a D-Bus
# call. SPEC.md's Scope section puts all of it out of the specification, which
# is why it lives here and not there.
# =============================================================================

# An icon *theme* namespace, not a filename. It belongs to the implementing
# tool; SPEC.md fixes the short id and leaves the prefix alone, so that two
# tools installing icons for one project do not collide. Changing it in a copy
# that has already installed icons orphans every one of them.
ICON_PREFIX = "console-colophon"
INSTALL_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def icon_name(key):
    """The theme name of the installed icon. A name, never a path."""
    return f"{ICON_PREFIX}-{short_hash(key)}"


def profile_name(key):
    """The profile's display name, and what setProfile matches on."""
    return f"{project_name(key)} [{short_hash(key, 6)}]"


def profile_filename(key):
    """The file that profile is written to."""
    return f"{ICON_PREFIX}-{short_hash(key)}.profile"


def profile_body(key, parent="FALLBACK/"):
    """The .profile contents: three keys, so the switch changes only the icon."""
    return (
        "[General]\n"
        f"Name={profile_name(key)}\n"
        f"Parent={parent}\n"
        f"Icon={icon_name(key)}\n"
    )


def icon_theme_root():
    """The user's hicolor tree, which merges with the system theme."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return pathlib.Path(data_home) / "icons" / "hicolor"


def konsole_profile_dir():
    """Where Konsole reads user profiles from."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return pathlib.Path(data_home) / "konsole"


def install_icon(key, root=None, sizes=INSTALL_SIZES, **render_kwargs):
    """Write one PNG per size plus a scalable SVG. Returns the paths written."""
    root = pathlib.Path(root) if root else icon_theme_root()
    name = icon_name(key)
    written = []
    for size in sizes:
        directory = root / f"{size}x{size}" / "apps"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.png"
        target.write_bytes(render_png(key, fit_block(size), edge=size,
                                      **render_kwargs))
        written.append(target)

    scalable = root / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    target = scalable / f"{name}.svg"
    target.write_text(render_svg(key, ARTIFACT_BLOCK, **render_kwargs))
    written.append(target)
    return written


def installed_icons(root=None):
    """Every identicon this tool has installed, as {icon name: [paths]}."""
    root = pathlib.Path(root) if root else icon_theme_root()
    found = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob(f"*/apps/{ICON_PREFIX}-*")):
        found.setdefault(path.stem, []).append(path)
    return found


def remove_icon(name, root=None):
    """Delete every file of one installed icon. Returns the paths removed."""
    root = pathlib.Path(root) if root else icon_theme_root()
    removed = []
    for path in sorted(root.glob(f"*/apps/{name}.*")):
        path.unlink()
        removed.append(path)
    return removed


def install_profile(key, directory=None, parent="FALLBACK/"):
    """Write the generated profile. Returns the path written."""
    directory = pathlib.Path(directory) if directory else konsole_profile_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / profile_filename(key)
    target.write_text(profile_body(key, parent))
    return target


def installed_profiles(directory=None):
    """Every profile this tool has written, sorted."""
    directory = pathlib.Path(directory) if directory else konsole_profile_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{ICON_PREFIX}-*.profile"))


# ---- D-Bus ----
#
# setProfile is Q_SCRIPTABLE and setIconName is not, so the tab-bar icon is
# reachable only through a generated profile that carries Icon=.
#
# The third route -- an identicon on the session toolbar itself -- needs a C++
# IKonsolePlugin. Konsole installs no plugin headers, so it cannot be built out
# of tree at all.

SESSION_IFACE = "org.kde.konsole.Session"
QDBUS_CANDIDATES = ("qdbus6", "qdbus-qt6", "qdbus")

BADGE_METHODS = (
    "setBadgeEnabled",
    "setBadgeText",
    "setBadgeColor",
    "setBadgeTextOnly",
    "setBadgeTransparency",
    "setBadgeFontFamily",
    "setBadgeFontSize",
)


class DBusError(RuntimeError):
    """The bus could not be reached, or a call to it failed."""


def find_qdbus():
    """The first qdbus on PATH, or None."""
    for candidate in QDBUS_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def find_gdbus():
    """gdbus on PATH, or None."""
    return shutil.which("gdbus")


def _run(argv):
    """Run a command, raising DBusError on a non-zero exit."""
    completed = subprocess.run(argv, capture_output=True, text=True)
    if completed.returncode != 0:
        raise DBusError((completed.stderr or completed.stdout).strip()
                        or f"{argv[0]} failed")
    return completed.stdout


def dbus_call(service, path, method, args=(), qdbus=None):
    """Call a method on a Konsole session. Argument list, never a shell string."""
    qdbus = qdbus or find_qdbus()
    if qdbus:
        return _run([qdbus, service, path, f"{SESSION_IFACE}.{method}",
                     *[str(a) for a in args]])
    gdbus = find_gdbus()
    if not gdbus:
        raise DBusError("neither qdbus nor gdbus is on PATH")
    argv = [gdbus, "call", "--session", "--dest", service, "--object-path", path,
            "--method", f"{SESSION_IFACE}.{method}"]
    argv += [str(a) for a in args]
    return _run(argv)


def dbus_members(service, path):
    """The method names the object exposes, for capability probing."""
    qdbus = find_qdbus()
    if qdbus:
        listing = _run([qdbus, service, path])
        names = set()
        for line in listing.splitlines():
            line = line.strip()
            if not line:
                continue
            head = line.split("(")[0].split()[-1]
            names.add(head.rsplit(".", 1)[-1])
        return names
    gdbus = find_gdbus()
    if not gdbus:
        raise DBusError("neither qdbus nor gdbus is on PATH")
    xml = _run([gdbus, "introspect", "--session", "--dest", service,
                "--object-path", path, "--xml"])
    names = set()
    for line in xml.splitlines():
        line = line.strip()
        if line.startswith("<method "):
            names.add(line.split('name="', 1)[1].split('"', 1)[0])
    return names


def list_konsole_services():
    """Every org.kde.konsole* name on the session bus."""
    qdbus = find_qdbus()
    if qdbus:
        return sorted(n for n in _run([qdbus]).split() if n.startswith("org.kde.konsole"))
    gdbus = find_gdbus()
    if not gdbus:
        return []
    out = _run([gdbus, "call", "--session", "--dest", "org.freedesktop.DBus",
                "--object-path", "/org/freedesktop/DBus",
                "--method", "org.freedesktop.DBus.ListNames"])
    return sorted({tok.strip("'\", []()") for tok in out.split(",")
                   if "org.kde.konsole" in tok})


def list_sessions(service):
    """The /Sessions/N object paths under one service."""
    qdbus = find_qdbus()
    if not qdbus:
        return []
    return sorted(line.strip() for line in _run([qdbus, service]).splitlines()
                  if line.strip().startswith("/Sessions/"))


def resolve_session(spec=None):
    """(service, path) for the session to act on: the environment, else the only one."""
    if spec:
        if ":" not in spec:
            raise DBusError(f"session spec must be service:/Sessions/N, got {spec!r}")
        service, path = spec.split(":", 1)
        return service, path

    service = os.environ.get("KONSOLE_DBUS_SERVICE")
    path = os.environ.get("KONSOLE_DBUS_SESSION")
    if service and path:
        return service, path

    services = list_konsole_services()
    if len(services) == 1:
        sessions = list_sessions(services[0])
        if len(sessions) == 1:
            return services[0], sessions[0]
    raise DBusError(
        "not running inside Konsole and could not pick a session unambiguously; "
        "pass --session service:/Sessions/N (see the `sessions` command)"
    )


# =============================================================================
# Commands
# =============================================================================

def _resolve_from_args(args):
    """(key, source) for whatever path the command was given."""
    return resolve_key_for(getattr(args, "path", None),
                           getattr(args, "seed", None))


def _key_from_args(args):
    """The key for whatever path the command was given."""
    return _resolve_from_args(args)[0]


def _render_kwargs(args):
    """The chroma, lightness and background a render takes."""
    background = None
    if getattr(args, "background", None):
        text = args.background.lstrip("#")
        if len(text) != 6:
            raise SystemExit("--background wants a six digit hex colour")
        background = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    return {
        "chroma": args.chroma,
        "lightness": args.lightness,
        "background": background,
    }


def cmd_install(args):
    """Write the icon into the user's hicolor tree."""
    key = _key_from_args(args)
    written = install_icon(key, **_render_kwargs(args))
    print(f"icon {icon_name(key)}")
    for path in written:
        print(f"  {path}")
    print()
    print("Konsole reads profile icons through QIcon::fromTheme, which caches. A")
    print("running Konsole may not show a brand new icon until it restarts.")
    return 0


def cmd_list(args):
    """List what this tool has installed."""
    icons = installed_icons()
    profiles = installed_profiles()
    if not icons and not profiles:
        print("nothing installed")
        return 0
    for name, paths in icons.items():
        print(f"{name}  ({len(paths)} files)")
    for path in profiles:
        print(f"{path.name}  ->  {path}")
    return 0


def cmd_uninstall(args):
    """Remove one project's icon and profile, or everything this tool installed."""
    if args.all:
        names = list(installed_icons())
        profiles = installed_profiles()
    else:
        key = _key_from_args(args)
        names = [icon_name(key)]
        candidate = konsole_profile_dir() / profile_filename(key)
        profiles = [candidate] if candidate.exists() else []

    removed = 0
    for name in names:
        for path in remove_icon(name):
            print(f"removed {path}")
            removed += 1
    for path in profiles:
        path.unlink()
        print(f"removed {path}")
        removed += 1
    if not removed:
        print("nothing to remove")
    return 0


def cmd_sessions(args):
    """List the Konsole sessions on the bus."""
    services = list_konsole_services()
    if not services:
        print("no Konsole instance is on the session bus")
        return 1
    for service in services:
        print(service)
        for path in list_sessions(service):
            print(f"  {service}:{path}")
    return 0


def cmd_probe(args):
    """Report which of the two routes this Konsole build actually offers."""
    service, path = resolve_session(args.session)
    print(f"session   {service}:{path}")
    members = dbus_members(service, path)
    print(f"members   {len(members)}")
    print()
    print("badge route")
    for method in BADGE_METHODS:
        print(f"  {'yes' if method in members else 'NO '}  {method}")
    print()
    print("profile route")
    for method in ("setProfile", "profile"):
        print(f"  {'yes' if method in members else 'NO '}  {method}")
    print()
    print("not scriptable, hence no direct tab-icon route")
    print("  NO   setIconName")
    return 0


def cmd_badge(args):
    """Route one: put one or two characters on the session badge."""
    key = _key_from_args(args)
    service, path = resolve_session(args.session)
    members = dbus_members(service, path)

    if args.clear:
        dbus_call(service, path, "setBadgeEnabled", ["false"])
        print(f"badge cleared on {service}:{path}")
        return 0

    label = args.label or badge_label(key)
    dbus_call(service, path, "setBadgeText", [label])
    dbus_call(service, path, "setBadgeEnabled", ["true"])
    print(f"badge text  {label}")

    colour = hex_colour(identicon_colour(key, args.chroma, args.lightness))
    if "setBadgeColor" in members:
        dbus_call(service, path, "setBadgeColor", [colour])
        print(f"badge colour {colour}")
    else:
        print(f"badge colour {colour} NOT APPLIED - setBadgeColor absent from introspection")
        print("             QColor has no D-Bus metatype registered in Konsole")
    return 0


def cmd_profile(args):
    """Route two: generate a profile carrying the icon, and optionally switch to it."""
    key = _key_from_args(args)
    install_icon(key, **_render_kwargs(args))
    target = install_profile(key, parent=args.parent)
    name = profile_name(key)
    print(f"icon     {icon_name(key)}")
    print(f"profile  {name}")
    print(f"         {target}")

    if not args.apply:
        print()
        print("re-run with --apply to switch the current tab to it")
        return 0

    service, path = resolve_session(args.session)
    dbus_call(service, path, "setProfile", [name])
    active = dbus_call(service, path, "profile").strip()
    print(f"applied  {service}:{path}")
    print(f"now on   {active or '(empty)'}")
    if active != name:
        print()
        print("setProfile matches against already-loaded profiles and no-ops on a")
        print("miss. A profile written after Konsole started is not loaded yet;")
        print("open Settings, Manage Profiles, or restart Konsole, then retry.")
        return 1
    return 0


def cmd_demo(args):
    """Probe, then exercise both routes on one session."""
    key = _key_from_args(args)
    print(f"=== {key} ===")
    print(render_ansi(key))
    print()
    for step, handler in (("probe", cmd_probe), ("badge", cmd_badge),
                          ("profile", cmd_profile)):
        print(f"--- {step} ---")
        try:
            handler(args)
        except DBusError as error:
            print(f"skipped: {error}")
        print()
    return 0


def cmd_emit(args):
    """Print the identicon to stdout, in one of the styles SPEC.md defines.

    Stdout and nothing else. An earlier version of this in Repository-Identicon
    opened `/dev/tty` and swallowed every error to exit 0, because it was
    written to be a Claude Code hook; both of those are properties of a caller,
    not of a rendering, and neither came with it.
    """
    key, source = _resolve_from_args(args)
    sys.stdout.write(render(
        key,
        style=args.style,
        source=source,
        depth=resolve_colour_depth(args.colour),
        protocol=resolve_protocol(args.protocol),
        size=args.size,
        **_render_kwargs(args),
    ))
    return 0


def cmd_derive(args):
    """Print the grid and colour for a key, in the shape `validate` expects."""
    key = args.key
    print(json.dumps({
        "key": key,
        "grid": ["".join("1" if cell else "0" for cell in row)
                 for row in identicon_grid(key)],
        "colour": hex_colour(identicon_colour(key)),
    }))
    return 0


def cmd_doctor(args):
    """Report the environment this tool depends on. Writes nothing."""
    sibling = text_module_path()
    print(f"text-identicon.py {sibling if sibling.is_file() else 'NOT FOUND'}")
    print(f"protocol         {resolve_protocol()}")
    print(f"colour depth     {resolve_colour_depth()}")
    print(f"qdbus            {find_qdbus() or 'NOT FOUND'}")
    print(f"gdbus            {find_gdbus() or 'NOT FOUND'}")
    print(f"icon theme root  {icon_theme_root()}")
    print(f"profile dir      {konsole_profile_dir()}")
    print(f"in Konsole       {'yes' if os.environ.get('KONSOLE_DBUS_SESSION') else 'no'}")
    for variable in ("KONSOLE_DBUS_SERVICE", "KONSOLE_DBUS_SESSION", "KONSOLE_VERSION"):
        print(f"  {variable}={os.environ.get(variable, '')}")
    print(f"icon prefix      {ICON_PREFIX}")
    print(f"icons installed  {len(installed_icons())}")
    print(f"profiles written {len(installed_profiles())}")
    try:
        services = list_konsole_services()
        print(f"konsole services {', '.join(services) if services else 'none'}")
    except DBusError as error:
        print(f"konsole services unavailable: {error}")
    return 0


# =============================================================================
# Command line
# =============================================================================

def build_parser():
    """Every subparser, and which function runs it."""
    parser = argparse.ArgumentParser(
        prog="console-colophon",
        description="Per-project identicons on the desktop: the XDG icon theme, "
                    "and Konsole tabs over the session D-Bus interface.",
    )
    parser.add_argument("--version", action="version",
                        version=f"console-colophon {VERSION} "
                                f"(mapping version {MAPPING_VERSION})")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target, *, path=True, render=False, session=False):
        if path:
            target.add_argument("path", nargs="?", help="project path (default: cwd)")
            target.add_argument("--seed", "--key", dest="seed",
                                help="override the derived seed outright")
        else:
            target.set_defaults(seed=None)
        if render:
            target.add_argument("--chroma", type=float, default=MARK_CHROMA)
            target.add_argument("--lightness", type=float, default=MARK_LIGHTNESS)
            target.add_argument("--background", help="six digit hex; default transparent")
        else:
            target.set_defaults(chroma=MARK_CHROMA, lightness=MARK_LIGHTNESS,
                                background=None)
        if session:
            target.add_argument("--session",
                                help="service:/Sessions/N; default from the environment")
        else:
            target.set_defaults(session=None)

    install = sub.add_parser("install", help="install the identicon into the user icon theme")
    add_common(install, render=True)
    install.set_defaults(func=cmd_install)

    listing = sub.add_parser("list", help="list installed identicons and profiles")
    add_common(listing, path=False)
    listing.set_defaults(func=cmd_list)

    uninstall = sub.add_parser("uninstall", help="remove installed identicons and profiles")
    add_common(uninstall)
    uninstall.add_argument("--all", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    sessions = sub.add_parser("sessions", help="list Konsole sessions on the bus")
    add_common(sessions, path=False)
    sessions.set_defaults(func=cmd_sessions)

    probe = sub.add_parser("probe", help="report which D-Bus methods this Konsole exposes")
    add_common(probe, path=False, session=True)
    probe.set_defaults(func=cmd_probe)

    badge = sub.add_parser("badge", help="route one: set the session badge")
    add_common(badge, render=True, session=True)
    badge.add_argument("--label", help="override the derived one or two character label")
    badge.add_argument("--clear", action="store_true", help="disable the badge instead")
    badge.set_defaults(func=cmd_badge)

    profile = sub.add_parser("profile", help="route two: generate a profile carrying the icon")
    add_common(profile, render=True, session=True)
    profile.add_argument("--parent", default="FALLBACK/", help="profile to inherit from")
    profile.add_argument("--apply", action="store_true", help="switch the session to it")
    profile.set_defaults(func=cmd_profile)

    demo = sub.add_parser("demo", help="probe, then exercise both routes on one session")
    add_common(demo, render=True, session=True)
    demo.add_argument("--label", default=None)
    demo.add_argument("--parent", default="FALLBACK/")
    demo.set_defaults(func=cmd_demo, clear=False, apply=True)

    emit = sub.add_parser(
        "emit",
        help="print the identicon to stdout, in one of the specified styles",
        description="Writes to stdout and nothing else. icon sends a real "
                    "image where the terminal takes one and falls back to "
                    "text where it does not.")
    add_common(emit, render=True)
    emit.add_argument("--style", choices=STYLES, default="icon")
    emit.add_argument("--protocol", choices=("auto", *PROTOCOLS), default="auto")
    emit.add_argument("--size", type=int, default=INLINE_SIZE,
                      help="inline image side in pixels")
    emit.add_argument("--colour", choices=("auto", *COLOUR_DEPTHS), default="auto")
    emit.set_defaults(func=cmd_emit)

    derive = sub.add_parser(
        "derive",
        help="print the grid and colour for a key, for conformance checking",
        description="The shape `repository-identicon validate` expects, so this "
                    "vendored copy can be held to the pinned vectors from outside.")
    add_common(derive, path=False)
    derive.add_argument("key", help="a full key, e.g. 3:github.com/owner/repo")
    derive.set_defaults(func=cmd_derive)

    doctor = sub.add_parser("doctor", help="environment report")
    add_common(doctor, path=False)
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv=None):
    """Parse, dispatch, and turn the two expected failures into one line each."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DBusError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except UnknownMappingVersion as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    sys.exit(main())
