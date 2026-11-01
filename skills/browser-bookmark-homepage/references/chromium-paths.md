# Chromium profile paths

Paths are under the OS user profile. Prefer the active "Default" profile unless the user names another (`Profile 1`, etc.).

## Windows

| Browser | User Data root (append `\Default\Bookmarks` and `\Default\History`) |
| --- | --- |
| Google Chrome | `%LOCALAPPDATA%\Google\Chrome\User Data` |
| Microsoft Edge | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| Brave | `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data` |
| Perplexity Comet | `%LOCALAPPDATA%\Perplexity\Comet\User Data` |

## macOS

| Browser | User Data root |
| --- | --- |
| Chrome | `~/Library/Application Support/Google/Chrome` |
| Edge | `~/Library/Application Support/Microsoft Edge` |
| Brave | `~/Library/Application Support/BraveSoftware/Brave-Browser` |
| Comet | `~/Library/Application Support/Perplexity/Comet` (verify on device if missing) |

## Linux

| Browser | User Data root |
| --- | --- |
| Chrome | `~/.config/google-chrome` |
| Chromium | `~/.config/chromium` |
| Edge | `~/.config/microsoft-edge` |
| Brave | `~/.config/BraveSoftware/Brave-Browser` |

## Notes

- `Bookmarks` is JSON UTF-8. `History` is SQLite; copy it before querying if the browser is open.
- Portable / enterprise installs may live elsewhere; ask for the folder that contains `Bookmarks` and `History`.
