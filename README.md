# Console-Colophon

Per-project identicons for Konsole tabs, over the session D-Bus interface. Every
project gets a stable colour and pattern, so a wall of terminal tabs tells you
which is which without reading any of them.

```bash
python3 console-colophon.py install     # into the user icon theme
python3 console-colophon.py badge       # paint the mark over the session
python3 console-colophon.py profile --apply
python3 console-colophon.py doctor      # what this machine can actually do
```

## Two routes, because Konsole only offers two

`org.kde.konsole.Session` exposes `setBadgeText` and `setBadgeColor` as
`Q_SCRIPTABLE`, but **not** `setIconName`. So:

- **badge** paints a one or two character label over the terminal view. Direct,
  immediate, and gone when the session ends.
- **profile** generates a `.profile` carrying `Icon=`, and switches the session
  to it. Indirect, but it reaches the tab bar, which the badge cannot.

A third route — an identicon on the session toolbar — would need a C++
`IKonsolePlugin`. Konsole installs no plugin headers, so it cannot be built out
of tree at all.

## This is a delivery, not the standard

The derivation lives in
[`Repository-Identicon`](https://github.com/Justin-Maxwell/Repository-Identicon),
which is the specification, the pinned vectors and the reference
implementation. Everything above the `Konsole and D-Bus` banner in
`console-colophon.py` is a **vendored copy** of it.

Vendoring is the intended shape rather than a shortcut. Independent
implementations agree because they reproduce the same `vectors.json`, not
because they share an import — and some consumers have no dependency mechanism
at all. `vectors.json` is committed here and `tests/` holds the copy to it:

```bash
python3 -m unittest discover -s tests -t tests
```

If that fails, the copy has drifted. Fix the derivation upstream and re-vendor;
do not edit it here.

## What it writes, and where

| path | what |
|---|---|
| `~/.local/share/icons/hicolor/<size>/apps/console-colophon-<short id>.png` | theme icons, eight sizes |
| `~/.local/share/konsole/console-colophon-<short id>.profile` | the generated profile |

Nothing else, and nothing on the network. `uninstall` removes both.

### The icon prefix, and why old names are still swept

The specification fixes the twelve character short id and leaves the prefix to
the implementing tool, so that two tools marking one project do not collide.
This tool uses `console-colophon-`.

It also sweeps `repository-identicon-` and `claude-state-identicon-`, the names
this code installed under before it moved here. `uninstall` globs for a prefix,
so a rename without the sweep would leave icons that the tool which created
them could no longer see, and only a human with `rm` could clear.

## Licence

MIT, in `LICENSE`. Deliberately more permissive than `Repository-Identicon`'s
AGPL-3.0-or-later: this is a small Konsole tool, and the argument for copyleft
on a specification does not carry over to the code that talks to a bus.
