# Permissions

What working in this repository causes Claude to run, and why.

**Documentation only.** Nothing here is installed automatically. It exists so
that the reason for a rule survives the prompt that requested it.

## The whole set

| rule | why |
|---|---|
| `Bash(python3 *)` | The conformance suite, this tool's own command line, and probes. |
| `Bash(qdbus *)`, `Bash(qdbus6 *)`, `Bash(gdbus *)` | Reading and calling the Konsole session interface. This is the point of the repository, and it cannot be exercised without a live bus. |

## What this one writes, unlike the specification repository

Repository-Identicon can claim that nothing writes outside it. **This
repository cannot, and that is precisely why it exists.** `install` and
`profile` write into the user's data directory, and `badge` and `profile
--apply` make live calls to a running Konsole:

| what | where |
|---|---|
| icons | `$XDG_DATA_HOME/icons/hicolor/<n>x<n>/apps/console-colophon-*.png` |
| a scalable icon | `$XDG_DATA_HOME/icons/hicolor/scalable/apps/console-colophon-*.svg` |
| profiles | `$XDG_DATA_HOME/konsole/console-colophon-*.profile` |
| D-Bus calls | `org.kde.konsole.Session` on the session bus |

All of it is namespaced by `ICON_PREFIX`, so `uninstall --all` takes back
exactly what this tool put there and nothing else. `doctor` reports the paths
before anything is written, and the test suite writes only into a temporary
directory.

Nothing reaches the network.
