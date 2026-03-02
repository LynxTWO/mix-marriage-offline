# Plugins and the offline marketplace

MMO separates the stable core from fast-evolving strategies.
Plugins are how strategy evolves without breaking contracts.

There are three plugin sources.
A repo plugin root (often `plugins/` in a checkout).
A user plugin directory (platform default shown below).
Packaged built-ins (installed distribution).

Default user plugin directory by platform.
Windows: `%LOCALAPPDATA%\mmo\plugins`  (e.g. `C:\Users\you\AppData\Local\mmo\plugins`)
macOS: `~/Library/Application Support/mmo/plugins`
Linux: `$XDG_DATA_HOME/mmo/plugins` or `~/.local/share/mmo/plugins`

Override with the `MMO_PLUGIN_DIR` environment variable or `--plugin-dir` flag.

Offline marketplace commands.
List the bundled marketplace entries:
mmo plugin list --format json

Write a deterministic local snapshot:
mmo plugin update

Install a plugin by ID:
mmo plugin install PLUGIN.SOME_ID

Discover installed plugins.
mmo plugins list --format json

Pro notes.
If a plugin ships UI metadata, it can be browsed in the GUI.
If you are developing plugins, use `mmo plugins ui-lint` to validate ui_layout and UI contracts together.