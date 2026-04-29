# Asana Portfolio Daily Status

A Claude Code / Cowork **scheduled task** that compiles a tidy, dated Markdown digest of
the most recent task-level comment on every active project in a configured Asana
portfolio, and saves it to a local folder.

The intended audience is teams who:

- Use Asana **portfolios** to group a recurring set of projects (e.g., a unit's active
  work).
- Tag projects with a **workflow-state custom field** ("Underway", "Stuck", "Scheduled",
  "Hold", etc.) so the digest can include the in-flight projects and skip the ones that
  aren't.
- Want a daily one-page summary written to a local folder — optionally one that a
  first-party sync client (Google Drive for Desktop, Dropbox, OneDrive, Syncthing,
  rclone) mirrors to a shared location.

This package contains the skill instructions, configuration knobs, install notes, an
example output, and a short design-rationale doc. Everything is plain Markdown and
plain text.

## What it does, concretely

Once a day (or on demand), the task:

1. Pulls every project in your Asana portfolio.
2. Filters out projects whose workflow-state field is in your "skip" list (e.g.,
   `Hold`, `Uncategorized`, `Requested`).
3. For each remaining project, finds the **single most recent task-level comment**
   across the project's recently-modified tasks. (Project-level status updates are used
   only as a fallback.)
4. Writes a flat, link-rich Markdown file like this:

   ```
   **My Portfolio — April 29, 2026**

   - [Project A](https://app.asana.com/...) (Alex Doe)
     - Finished the metadata crosswalk; QA next week.
   - [Project B](https://app.asana.com/...) (Jamie Lee) *(Stuck)*
     - Waiting on vendor reply re: OAI-PMH endpoint.
   ```

5. Saves the file as `<FILE_PREFIX>-Status-YYYY-MM-DD.md` in your configured output
   folder.

See [`examples/sample-output.md`](examples/sample-output.md) for a longer fictional
example.

## Why a scheduled task and not a script?

A standalone Python script would also work for this — and if you prefer that, the
algorithm in [`skill/SKILL.md`](skill/SKILL.md) maps cleanly onto the official
[python-asana](https://github.com/Asana/python-asana) library. The reason this version
is packaged as a Claude scheduled task is:

- It runs entirely through MCP connectors that you've already authorized in your Claude
  app, so there's no additional API token, secret store, or `cron` setup to maintain.
- The agent can fall back gracefully on partial data (a project with no comments, a
  custom field that isn't set, a task that 404s) and produce a useful report rather
  than crashing.
- The output is meant to be human-edited if needed — Markdown in a synced folder is
  about as portable and minimal-computing-friendly as a daily report gets.

## What's in this package

```
asana-portfolio-daily-status/
├── README.md            ← you are here
├── INSTALL.md           ← step-by-step setup
├── CONFIGURATION.md     ← list of placeholders to fill in
├── skill/
│   └── SKILL.md         ← the actual scheduled-task instructions
├── examples/
│   └── sample-output.md ← fictional example of a daily digest
└── docs/
    └── design-notes.md  ← why the skill is shaped the way it is
```

The skill file (`skill/SKILL.md`) is the only file the Claude agent actually executes.
Everything else is documentation aimed at humans installing or modifying the workflow.

## Quick start

1. **Install the skill into your Claude scheduled tasks folder.** See
   [`INSTALL.md`](INSTALL.md).
2. **Edit the placeholders** (`<PORTFOLIO_GID>`, `<OUTPUT_FOLDER>`, etc.) at the top of
   `skill/SKILL.md` to match your environment. The full list is in
   [`CONFIGURATION.md`](CONFIGURATION.md).
3. **Schedule it** through Claude's `schedule` skill or your scheduled-tasks UI (a
   weekday morning cron like `0 9 * * 1-5` is typical).
4. **Run it once manually** to confirm the output folder, custom-field name, and
   exclusion list are all set the way you expect.

## Requirements

- A working Asana account with API access (any paid plan; the free tier exposes a
  subset of the needed endpoints but custom fields are paid-only).
- The Asana MCP connector enabled in your Claude app, with at minimum:
  `get_items_for_portfolio`, `get_tasks`, `get_task`.
- A local writable folder for the daily Markdown files. Optional: a sync client
  pointed at that folder if you want the file mirrored to a shared drive.

No Google APIs, no OAuth setup beyond the Asana connector, no third-party services.

## License & reuse

This package is released into the **public domain** under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/). Reuse, fork,
adapt, distribute, or rip apart freely, with or without attribution (if you want to be generous, 
just credit "Digital Collections Team, Hamilton College LITS". 

The original was developed in an academic library / digital collections context, 
but nothing in it is specific to that domain.

## Acknowledgements

Built on top of the Claude Agent SDK's MCP / scheduled-tasks framework and the public
Asana REST API. The "tight meeting-notes" output style was patterned after a
hand-maintained agenda template that predates the automation.
