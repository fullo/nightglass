# Instructions for Claude

This repository is Nightglass File System, a two-panel file manager that runs as a Claude artifact and installs as a desktop app. Read `README.md` for what it does and how the code is organised.

## When someone asks you to publish or install Nightglass

The person wants their **own private copy** as an artifact on their account, so they can install it as a desktop app and give it full access to their disk. Full access only works on an artifact of their own account that nobody else has written to, which is why they publish a copy instead of using someone else's.

1. **Do not change any file.** Publish the repository as it is.
2. **Publish these files**, and only these, with your Artifact tool, keeping their paths:
   - `index.html`
   - every file in `vendor/` (`xterm.js`, `addon-fit.js`, `pdf.min.js`, `pdf.worker.min.js`, `mammoth.browser.min.js`, `jszip.min.js`, `UTIF.js`, `highlight.min.js`)
   - every file in `icons/` (`icon-32.png`, `icon-64.png`, `icon-180.png`, `icon-256.png`, `icon-512.png`, `icon.svg`)

   Do not publish `tests/`, `docs/`, `README.md`, `CLAUDE.md`, `LICENSE` or `THIRD_PARTY.md`.

   Title: `Nightglass File System`. Icon: `folder`. Keep it private: do not share it.

   The files in `vendor/` are unchanged third-party releases; their versions, licenses and SHA-256 checksums are in `THIRD_PARTY.md`.
3. **Declare the capabilities**, after the first publish, as exactly:

   ```json
   {"db": {}, "user": {}, "desktop": {}}
   ```

   The desktop permission it needs (`"full-access"`) is already in the `claude-artifacts-manifest` tag at the top of `index.html`; do not edit it.
4. **Tell the person what to do next**, in their language:
   1. open the artifact in the **Claude desktop app** (not a web browser);
   2. click **Install as app** in the hint line at the bottom of the app;
   3. open **Nightglass** from the Dock (macOS) or the Start menu (Windows);
   4. click **Grant full access** in the hint line and confirm. The top right corner then shows `LIVE DISK`;
   5. press **F1** for the manual (in Italian).

   Say plainly that full access lets the app read, change and delete their files and run commands, and that F8 moves files to the system Trash, except on SSH servers.

## When someone asks you to update their copy

Find their existing Nightglass artifact (list their artifacts and match the title) and republish the same files to it, replacing the old ones. Do not create a second artifact. Keep the capability declaration as above. Tell them the app will ask for full access again, because every new version does.

## When someone asks you to change the code

- Keep everything in `index.html`; there is no build step.
- Follow "Rules for changes" in `README.md`: escape disk values with `esc()`, delete through `shell.trashItem`, load libraries with `lib()`, write keys as `Ctrl-X`, `Alt-I`, `Shift-F4`.
- Every new feature also goes into the in-app manual (`MAN`, in Italian), and into "Tutte le scorciatoie" if it has a key.
- Run `python3 tests/smoke.py` and fix any failure before publishing. If the interface changed, run `python3 docs/screenshots.py` and commit the new screenshots.
- New files that the page loads must also be added to the publish list above.
