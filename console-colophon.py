#!/usr/bin/env python3
"""Per-project identicons for Konsole tabs, over the session D-Bus interface.

Two compile-free routes to a per-tab project marker:

  badge    org.kde.konsole.Session exposes setBadgeText, setBadgeColor and
           friends as Q_SCRIPTABLE. Paints over the terminal view.
  profile  setProfile is Q_SCRIPTABLE while setIconName is not, so the tab-bar
           icon is reachable only by generating a profile that carries Icon=.

A third route, an identicon on the session toolbar itself, would need a C++
IKonsolePlugin. Konsole installs no plugin headers, so it cannot be built out
of tree at all.

**This is a delivery, not the standard.** The derivation below is vendored from
Repository-Identicon and held to its `vectors.json` by the suite in `tests/`.
Vendoring is the intended shape: independent implementations agree because they
reproduce the same pinned vectors, not because they share an import. Do not
"fix" the derivation here -- fix it there, and re-vendor.

Standard library only. Every subprocess is invoked with an argument list.
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import zlib

# ===========================================================================
# VENDORED from Repository-Identicon. Held to vectors.json by tests/.
# ===========================================================================
GRID = 5


# The reference fixes both rather than deriving them from the digest. Named
# once because they were previously written out at nine call sites, which is
# how a default drifts from the specification without anyone editing the rule.
SATURATION = 0.7


LIGHTNESS = 0.5


# An optional one-line seed at the repository top level, overriding the derived
# key. Committing it makes a project's identicon travel with the repository.
#
# Renamed away from `.claude-state-identicon`, which named one consumer of a
# specification that has several and none of which is Claude. The old name is
# still honoured on read: it is a file committed into other people's
# repositories, so dropping it would silently change their identicon, which is
# the one thing an override exists to prevent.
OVERRIDE_FILENAME = ".repository-identicon"


LEGACY_OVERRIDE_FILENAMES = (".claude-state-identicon",)


def normalise_key(path):
    """Reduce a filesystem path to a stable string.

    Expanded, made absolute, and stripped of any trailing separator, so that
    `~/src/foo`, `~/src/foo/` and a relative path to the same place all agree.

    This is the *fallback* key. Prefer resolve_key, which reaches the repository
    identity first — a path is not stable across machines, containers, or the
    per-session git worktrees the desktop app creates.
    """
    expanded = os.path.expanduser(str(path))
    absolute = os.path.abspath(expanded)
    return absolute.rstrip(os.sep) or os.sep


def normalise_remote_url(url):
    """Reduce a git remote URL to `host/owner/repo`, lowercased.

    Every way of naming one repository must collapse to one key, so an SSH
    checkout and an HTTPS checkout of the same project share an identicon:

        git@github.com:Owner/Repo.git
        https://github.com/Owner/Repo.git
        https://token@github.com/Owner/Repo
        ssh://git@github.com:2222/Owner/Repo.git   ->  github.com/owner/repo

    The host is kept, so `github.com/a/b` and `gitlab.com/a/b` stay distinct.
    Returns None for a local-path remote, which is no more portable than the
    working directory and so earns no special treatment.
    """
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
        # scp-like: [user@]host:path
        authority, _, path = url.partition(":")
    else:
        return None

    if "@" in authority:
        authority = authority.rpartition("@")[2]
    host = authority.partition(":")[0]  # drop any port

    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[: -len(".git")]

    parts = [part for part in path.split("/") if part]
    if not host or not parts:
        return None
    return "/".join([host] + parts).lower()


def _git(args, cwd=None):
    """Run a git command, returning stripped stdout or None if it fails.

    `cwd` of None means the current directory. It used to be interpolated
    straight into `git -C`, so a caller that passed None ran `git -C None`,
    which fails and comes back indistinguishable from "not a repository" --
    silent, and wrong in the direction that looks like a valid answer.
    `resolve_key` never hit it because it normalises the path first; anything
    calling these helpers directly did.
    """
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
    """The working tree root, or None outside a repository.

    In a worktree this is the worktree's own root, not the main checkout — which
    is exactly why it is not the key.
    """
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


def override_key(directory):
    """The committed seed at `directory`, if there is a usable one.

    The current name wins; a legacy name is honoured only when the current one
    is absent, so a repository carrying both is not left guessing.
    """
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


def resolve_key(path=None, explicit=None):
    """Return (key, source) for a project directory.

    Precedence, most specific first:

      explicit   given on the command line
      override   a committed .repository-identicon at the repository root
      remote     host/owner/repo from the git remote -- the portable one
      toplevel   the repository root path, for a repository with no remote
      path       the directory itself, outside a repository

    Only `remote` and `override` survive being cloned somewhere else. The two
    path-shaped sources are honest fallbacks, not equivalents.
    """
    directory = normalise_key(path if path else os.getcwd())
    if explicit:
        return explicit, "explicit"

    toplevel = repo_toplevel(directory)

    committed = override_key(toplevel or directory)
    if committed:
        return committed, "override"

    if toplevel:
        remote = normalise_remote_url(repo_remote_url(directory))
        if remote:
            return remote, "remote"
        return normalise_key(toplevel), "toplevel"

    return directory, "path"


def _digest(key):
    """MD5 as lowercase hex.

    Hex rather than bytes because the reference consumes the digest as *hex
    characters* -- one nibble per grid cell, and the last seven characters as
    the hue. Working in hex keeps this readable next to the reference instead
    of turning every rule into shifts and masks.
    """
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def identicon_grid(key):
    """Return the 5x5 grid as a list of rows of bools.

    Conforms to stewartlord/identicon.js, whose own comment reads:

        the first 15 characters of the hash control the pixels (even/odd)
        they are drawn down the middle first, then mirrored outwards

    So characters 0-4 fill the centre column top to bottom, 5-9 fill column 1
    and mirror it to 3, and 10-14 fill column 0 and mirror it to 4. Even is
    foreground. Pinned in vectors.json.
    """
    digest = _digest(key)
    grid = [[False] * GRID for _ in range(GRID)]
    for index in range(15):
        painted = int(digest[index], 16) % 2 == 0
        column, row = divmod(index, GRID)
        grid[row][2 - column] = painted
        grid[row][2 + column] = painted
    return grid


def identicon_hue(key):
    """Hue as a fraction of a turn, from the last seven hex characters.

    28 bits over 0xfffffff, per the reference. Drawn from the same digest as
    the grid, so colour and pattern cannot drift apart.
    """
    return int(_digest(key)[-7:], 16) / 0xFFFFFFF


def _quantise(value):
    """Round half up, not half to even.

    Specified this way because the spec has to be reimplementable in languages
    whose native rounding is half up. Python's round() is half to even, so
    following it would have made the spec quietly unportable.
    """
    return int(value * 255 + 0.5)


def _hsl_to_rgb(hue, saturation, lightness):
    """The reference's own HSL conversion, transliterated.

    Not `colorsys.hls_to_rgb`. The reference mutates `s` and `b` while building
    the sector table, and indexes it with `h|16` and `h|8` -- an integer trick
    for the six-sector rotation. Standard library conversion agrees on most
    inputs but this is a conformance target, so the arithmetic is reproduced
    rather than approximated. Verified against the library's own output for
    every key in vectors.json.
    """
    hue *= 6.0
    fraction = hue % 1

    spread = saturation * (lightness if lightness < 0.5 else 1 - lightness)
    high = lightness + spread
    doubled = spread * 2
    low = high - doubled

    sectors = [
        high,
        high - fraction * spread * 2,
        low,
        low,
        low + fraction * doubled,
        low + doubled,
    ]

    sector = int(hue)
    return (sectors[sector % 6],
            sectors[(sector | 16) % 6],
            sectors[(sector | 8) % 6])


def identicon_colour(key, saturation=0.7, lightness=0.5):
    """Return the foreground colour as an (r, g, b) triple of 0-255 ints.

    Defaults are the reference's: 70% saturation, 50% lightness, both fixed
    rather than derived. dgraham/identicon derives them from two further digest
    bytes; that variant was evaluated and not taken, because mixing two
    references would have produced a specification neither of them implements.
    """
    red, green, blue = _hsl_to_rgb(identicon_hue(key), saturation, lightness)
    return (_quantise(red), _quantise(green), _quantise(blue))


def hex_colour(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def short_hash(key, length=12):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


def project_name(key):
    """The last segment of the key, or the whole key if it has no separator."""
    return os.path.basename(key) or key


def badge_label(key, limit=2):
    """A one or two character label for the badge overlay.

    Initials where the project name has separators, otherwise the leading
    characters. Upper-cased, because the badge is small.
    """
    name = project_name(key)
    flat = name
    for separator in ("_", ".", " "):
        flat = flat.replace(separator, "-")
    words = [part for part in flat.split("-") if part]
    if len(words) >= 2:
        return "".join(word[0] for word in words[:limit]).upper()
    return name[:limit].upper()


def _geometry(size):
    """Cell size and margin for a square canvas.

    Cells are deliberately generous relative to the canvas so a 16px icon still
    reads as a pattern rather than a smudge.
    """
    cell = max(1, round(size / 5.5))
    if cell * GRID > size:
        cell = max(1, size // GRID)
    margin = (size - cell * GRID) // 2
    return cell, margin


def render_rgba(key, size, saturation=SATURATION, lightness=LIGHTNESS, background=None):
    """Return raw RGBA bytes for a square identicon of the given size."""
    grid = identicon_grid(key)
    red, green, blue = identicon_colour(key, saturation, lightness)
    cell, margin = _geometry(size)

    if background is None:
        back = bytes((0, 0, 0, 0))
    else:
        back = bytes(tuple(background) + (255,))
    fore = bytes((red, green, blue, 255))

    rows = []
    for y in range(size):
        row = bytearray()
        grid_y = (y - margin) // cell if cell else -1
        inside_y = margin <= y < margin + cell * GRID
        for x in range(size):
            grid_x = (x - margin) // cell if cell else -1
            inside_x = margin <= x < margin + cell * GRID
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


def render_png(key, size, **kwargs):
    return encode_png(render_rgba(key, size, **kwargs), size, size)


def render_svg(key, size=256, saturation=SATURATION, lightness=LIGHTNESS, background=None):
    grid = identicon_grid(key)
    colour = hex_colour(identicon_colour(key, saturation, lightness))
    cell, margin = _geometry(size)

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
                x = margin + column * cell
                y = margin + row * cell
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{colour}"/>'
                )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_ansi(key):
    """Terminal preview, two spaces per cell on a background colour."""
    grid = identicon_grid(key)
    red, green, blue = identicon_colour(key)
    lines = []
    for row in grid:
        line = ""
        for filled in row:
            line += f"\033[48;2;{red};{green};{blue}m  \033[0m" if filled else "  "
        lines.append(line)
    return "\n".join(lines)


# ===========================================================================
# Konsole and D-Bus. This half is this repository's own.
# ===========================================================================

# **The prefix names icons in the user's icon theme, nothing in a repository.**
# The specification fixes the short id and leaves the prefix to the implementing
# tool, precisely so two tools installing icons for one project do not collide.
#
# Renaming it would ordinarily orphan every icon already installed under the old
# name -- unremovable, because `uninstall` globs for the current prefix. So the
# old names are remembered and swept too. Same reasoning as
# LEGACY_OVERRIDE_FILENAMES upstream: a rename must not leave litter that the
# tool which created it can no longer see.
ICON_PREFIX = "console-colophon"
LEGACY_ICON_PREFIXES = ("repository-identicon", "claude-state-identicon")


def icon_prefixes():
    """Every prefix uninstall must sweep, current first."""
    return (ICON_PREFIX, *LEGACY_ICON_PREFIXES)


INSTALL_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def icon_name(key):
    """Theme icon name. Konsole's profile Icon= is a theme name, not a path."""
    return f"{ICON_PREFIX}-{short_hash(key)}"


def profile_name(key):
    """Display name of the generated profile, and what setProfile matches on."""
    return f"{project_name(key)} [{short_hash(key, 6)}]"


def profile_filename(key):
    return f"{ICON_PREFIX}-{short_hash(key)}.profile"


def profile_body(key, parent="FALLBACK/"):
    """The .profile file contents.

    Icon lives under [General], per Profile.cpp: {Icon, "Icon", GENERAL_GROUP}.
    Nothing else is set, so the profile inherits everything from its parent and
    the switch changes the icon alone.
    """
    return (
        "[General]\n"
        f"Name={profile_name(key)}\n"
        f"Parent={parent}\n"
        f"Icon={icon_name(key)}\n"
    )


def icon_theme_root():
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return pathlib.Path(data_home) / "icons" / "hicolor"


def konsole_profile_dir():
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return pathlib.Path(data_home) / "konsole"


def install_icon(key, root=None, sizes=INSTALL_SIZES, **render_kwargs):
    """Write one PNG per size into the user's hicolor tree. Returns the paths.

    hicolor under XDG_DATA_HOME merges with the system theme, so no index.theme
    of our own is needed for QIcon::fromTheme to find these.
    """
    root = pathlib.Path(root) if root else icon_theme_root()
    name = icon_name(key)
    written = []
    for size in sizes:
        directory = root / f"{size}x{size}" / "apps"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{name}.png"
        target.write_bytes(render_png(key, size, **render_kwargs))
        written.append(target)

    scalable = root / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    target = scalable / f"{name}.svg"
    target.write_text(render_svg(key, 256, **render_kwargs))
    written.append(target)
    return written


def installed_icons(root=None):
    """Every identicon this tool has installed, as {icon name: [paths]}."""
    root = pathlib.Path(root) if root else icon_theme_root()
    found = {}
    if not root.is_dir():
        return found
    for prefix in icon_prefixes():
        for path in sorted(root.glob(f"*/apps/{prefix}-*")):
            found.setdefault(path.stem, []).append(path)
    return found


def remove_icon(name, root=None):
    root = pathlib.Path(root) if root else icon_theme_root()
    removed = []
    for path in sorted(root.glob(f"*/apps/{name}.*")):
        path.unlink()
        removed.append(path)
    return removed


def install_profile(key, directory=None, parent="FALLBACK/"):
    directory = pathlib.Path(directory) if directory else konsole_profile_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / profile_filename(key)
    target.write_text(profile_body(key, parent))
    return target


def installed_profiles(directory=None):
    directory = pathlib.Path(directory) if directory else konsole_profile_dir()
    if not directory.is_dir():
        return []
    return sorted(path
                  for prefix in icon_prefixes()
                  for path in directory.glob(f"{prefix}-*.profile"))


SESSION_IFACE = "org.kde.konsole.Session"


QDBUS_CANDIDATES = ("qdbus6", "qdbus-qt6", "qdbus")


class DBusError(RuntimeError):
    pass


def find_qdbus():
    for candidate in QDBUS_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def find_gdbus():
    return shutil.which("gdbus")


def _run(argv):
    completed = subprocess.run(argv, capture_output=True, text=True)
    if completed.returncode != 0:
        raise DBusError((completed.stderr or completed.stdout).strip() or f"{argv[0]} failed")
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
    """Method names exposed on the object, for capability probing."""
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
    qdbus = find_qdbus()
    if not qdbus:
        return []
    return sorted(line.strip() for line in _run([qdbus, service]).splitlines()
                  if line.strip().startswith("/Sessions/"))


def resolve_session(spec=None):
    """Return (service, path) for the session to act on.

    With no spec, use the KONSOLE_DBUS_SERVICE and KONSOLE_DBUS_SESSION that
    Konsole exports into every session's environment, so running this inside
    the tab you want marked just works.
    """
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


def _resolve_from_args(args):
    return resolve_key(getattr(args, "path", None), getattr(args, "key", None))


def _key_from_args(args):
    return _resolve_from_args(args)[0]


def _render_kwargs(args):
    background = None
    if getattr(args, "background", None):
        text = args.background.lstrip("#")
        if len(text) != 6:
            raise SystemExit("--background wants a six digit hex colour")
        background = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    return {
        "saturation": args.saturation,
        "lightness": args.lightness,
        "background": background,
    }


def cmd_install(args):
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
    services = list_konsole_services()
    if not services:
        print("no Konsole instance is on the session bus")
        return 1
    for service in services:
        print(service)
        for path in list_sessions(service):
            print(f"  {service}:{path}")
    return 0


BADGE_METHODS = (
    "setBadgeEnabled",
    "setBadgeText",
    "setBadgeColor",
    "setBadgeTextOnly",
    "setBadgeTransparency",
    "setBadgeFontFamily",
    "setBadgeFontSize",
)


def cmd_probe(args):
    """Report which of the two routes this Konsole build actually offers.

    setBadgeColor takes a QColor, which is not a basic D-Bus type. Konsole
    registers no metatype for it, so it may be absent from introspection even
    though the header marks it Q_SCRIPTABLE. That is exactly what this checks.
    """
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

    colour = hex_colour(identicon_colour(key, args.saturation, args.lightness))
    if "setBadgeColor" in members:
        dbus_call(service, path, "setBadgeColor", [colour])
        print(f"badge colour {colour}")
    else:
        print(f"badge colour {colour} NOT APPLIED - setBadgeColor absent from introspection")
        print("             QColor has no D-Bus metatype registered in Konsole")
    return 0


def cmd_profile(args):
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


def cmd_doctor(args):
    """The Konsole half of what used to be one report.

    Repository-Identicon's doctor also reported whether text-identicon.py sat
    beside it. That belongs there; this reports the desktop and the bus.
    """
    print(f"qdbus            {find_qdbus() or 'NOT FOUND'}")
    print(f"gdbus            {find_gdbus() or 'NOT FOUND'}")
    print(f"icon theme root  {icon_theme_root()}")
    print(f"profile dir      {konsole_profile_dir()}")
    print(f"icon prefix      {ICON_PREFIX}")
    print(f"  also swept     {', '.join(LEGACY_ICON_PREFIXES)}")
    print(f"in Konsole       {'yes' if os.environ.get('KONSOLE_DBUS_SESSION') else 'no'}")
    for variable in ("KONSOLE_DBUS_SERVICE", "KONSOLE_DBUS_SESSION", "KONSOLE_VERSION"):
        print(f"  {variable}={os.environ.get(variable, '')}")
    print(f"icons installed  {len(installed_icons())}")
    print(f"profiles written {len(installed_profiles())}")
    try:
        services = list_konsole_services()
        print(f"konsole services {', '.join(services) if services else 'none'}")
    except DBusError as error:
        print(f"konsole services unavailable: {error}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="console-colophon",
        description="Per-project identicons for Konsole tabs, over the session "
                    "D-Bus interface.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target, *, path=True, render=False, session=False):
        if path:
            target.add_argument("path", nargs="?", help="project path (default: cwd)")
            target.add_argument("--key", help="override the derived key outright")
        else:
            target.set_defaults(key=None)
        if render:
            target.add_argument("--saturation", type=float, default=SATURATION)
            target.add_argument("--lightness", type=float, default=LIGHTNESS)
            target.add_argument("--background", help="six digit hex; default transparent")
        else:
            target.set_defaults(saturation=SATURATION, lightness=LIGHTNESS, background=None)
        if session:
            target.add_argument("--session",
                                help="service:/Sessions/N; default from the "
                                     "environment")
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

    profile = sub.add_parser(
        "profile", help="route two: generate a profile carrying the icon")
    add_common(profile, render=True, session=True)
    profile.add_argument("--parent", default="FALLBACK/", help="profile to inherit from")
    profile.add_argument("--apply", action="store_true", help="switch the session to it")
    profile.set_defaults(func=cmd_profile)

    demo = sub.add_parser("demo", help="probe, then exercise both routes on one session")
    add_common(demo, render=True, session=True)
    demo.add_argument("--label", default=None)
    demo.add_argument("--parent", default="FALLBACK/")
    demo.set_defaults(func=cmd_demo, clear=False, apply=True)

    doctor = sub.add_parser("doctor", help="environment report")
    add_common(doctor, path=False)
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DBusError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # Piping into head closes the pipe early. Retarget stdout at devnull so
        # the interpreter's own flush at exit does not report it a second time.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    sys.exit(main())
