# Console Colophon

![](.identicon/repository-identicon.svg)

Per-project identicons on the desktop: the XDG icon theme, and Konsole tabs.

A project's identicon is derived from the project itself — its git remote — by
the [Repository Identicon specification](../Repository-Identicon). That
specification says how a key becomes a pattern and a colour, and stops there.
This tool is one of the places that mark is put in front of a human.

```bash
python3 /path/to/console-colophon.py install     # the icon, into ~/.local/share/icons
python3 /path/to/console-colophon.py profile --apply   # a Konsole profile, and switch to it
```

## The two routes onto a Konsole tab, and why there are two

`setIconName` is not `Q_SCRIPTABLE`, so nothing on the session bus can put an
icon on a tab directly. Both routes here are ways around that.

**The profile route.** Generate a Konsole profile whose only content is
`Icon=<theme name>`, install the icon into the user's hicolor tree, and call
`setProfile`. The profile inherits everything else from its parent, so the
switch changes the icon and nothing else.

`setProfile` matches against already-loaded profiles and no-ops on a miss, so a
profile written after Konsole started is not switched to until Konsole reloads.
`profile --apply` reports that rather than claiming success.

**The badge route.** `setBadgeText` and `setBadgeEnabled` put one or two
characters on the tab. `setBadgeColor` takes a `QColor`, which is not a basic
D-Bus type and for which Konsole registers no metatype, so it can be missing
from introspection even where the header marks it scriptable. `badge` checks
before calling and says so when the colour could not be applied.

`probe` reports which of the two your build actually offers.

A third route — an identicon drawn on the session toolbar itself — needs a C++
`IKonsolePlugin`. Konsole installs no plugin headers, so it cannot be built out
of tree at all.

## Commands

| | |
|---|---|
| `install` | write the icon into the user's hicolor tree: eight sizes and a scalable SVG |
| `list` | what this tool has installed |
| `uninstall` | take one project's icon and profile back out, or `--all` |
| `profile` | generate the profile; `--apply` switches the session to it |
| `badge` | set the badge text, and its colour where the build allows |
| `probe` | which D-Bus methods this Konsole exposes |
| `sessions` | what is on the session bus |
| `demo` | probe, then exercise both routes on one session |
| `derive` | the grid and colour for a key, for conformance checking |
| `doctor` | the environment this tool depends on. Writes nothing. |

## The derivation is vendored, not imported

`console-colophon.py` carries its own copy of the key resolution, the grid, the
colour and the renderers. That is the intended shape rather than a shortcut:
the whole point of pinned vectors is that independent implementations agree
without a shared registry or a package manager.

What holds this copy to the specification is `tests/`, which reproduces every
vector in `vectors.json` — the same file, copied from the specification
repository. The copy can also be checked from outside:

```bash
python3 /path/to/repository-identicon.py validate -- python3 console-colophon.py derive
```

Ten of ten, or this is not a repository identicon.

```bash
python3 -m unittest discover -s tests -t tests
```

## What is deliberately not here

`SPEC.md` § Scope draws the line at the side effect: **in** is how to derive a
key and how a key reaches each medium; **out** is where a tool chooses to
display the result. Everything in this repository is on the far side of that
line, and everything on the near side stays in the specification repository —
the key, the grid, the colour, the derived names, every rendering, and `apply`,
which writes the artifacts a repository commits.

The one thing this repository chooses for itself is `ICON_PREFIX`, which the
specification explicitly leaves to the implementing tool so that two tools
installing icons for one project do not collide. It is `console-colophon`.

## Licence

AGPL-3.0-or-later, in `LICENSE`, inherited from the specification repository
and provisional there for the same reason: it is a poor fit for something meant
to be reimplemented freely.
