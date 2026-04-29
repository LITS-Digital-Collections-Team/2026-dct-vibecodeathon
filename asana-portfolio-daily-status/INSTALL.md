# Installation

These instructions assume you are running Claude Code or the Claude desktop app
("Cowork") with the **Asana MCP** connector already authorized. If Asana isn't yet
connected, do that first — open Claude → Connectors → Asana, sign in, and approve the
default scope.

The skill itself is plain text. There is nothing to compile, install, or `pip install`.

## 1. Drop the skill into a scheduled-tasks folder

Claude Code / Cowork looks in a couple of locations for scheduled tasks. The most
portable choice on macOS / Linux is:

```
~/Documents/Claude/Scheduled/asana-portfolio-daily-status/SKILL.md
```

On Windows:

```
%USERPROFILE%\Documents\Claude\Scheduled\asana-portfolio-daily-status\SKILL.md
```

Copy `skill/SKILL.md` from this package into that path. Keep the folder name the same
as the skill's `name:` field in the YAML frontmatter (`asana-portfolio-daily-status`).

If your Claude install uses a different scheduled-tasks directory, point at that
instead — the only requirement is that Claude's `schedule` skill can find a folder
containing `SKILL.md` with valid frontmatter.

## 2. Fill in the placeholders

Open the copied `SKILL.md` and edit every value in `<ANGLE_BRACKETS>`. The full list,
with what each one means and how to discover it, is in
[`CONFIGURATION.md`](CONFIGURATION.md).

At minimum you must set:

- `<PORTFOLIO_GID>`
- `<PORTFOLIO_NAME>` and `<PORTFOLIO_DISPLAY_NAME>`
- `<OUTPUT_FOLDER>`
- `<FILE_PREFIX>`
- `<WORKFLOW_CATEGORY_FIELD>`
- The list of excluded values
- `<DEFAULT_ACTIVE_CATEGORY>`

Optional:

- `<RESPONSIBLE_FIELD>` — leave the placeholder in place if you don't have a custom
  responsible-person field; the skill will fall back to `owner.name`.

## 3. Confirm the output folder exists

The skill is intentionally cautious here — it will **not** create a missing output
folder. Create it yourself:

```bash
mkdir -p "/path/to/your/output/folder"
```

If you want the file synced to a shared drive (Google Drive, Dropbox, etc.), put the
folder somewhere your sync client already mirrors. The skill writes locally and stays
out of any cloud API.

## 4. Schedule it

Inside Claude, ask the agent to schedule the new skill, e.g.:

> Schedule the `asana-portfolio-daily-status` task to run weekday mornings at 9am.

That invokes the bundled `schedule` skill, which writes a cron-style entry like
`0 9 * * 1-5`. You can also do this through whatever scheduled-tasks UI your Claude
build exposes.

You may want to use a small jitter (a few minutes) so the morning kickoff doesn't
collide with other recurring tasks.

## 5. Smoke-test it

Run the task on demand once before relying on it:

> Run the `asana-portfolio-daily-status` task now.

Check that:

- The output file appears in `<OUTPUT_FOLDER>`.
- The skip counts in the summary line up with what you expected from your portfolio.
- The "responsible" parenthetical is set on most projects (this is the most common
  configuration miss — the custom-field name has to match exactly).
- A few projects' comment lines are recognizable to someone on the team.

If the file is empty, every project shows `*[No recent activity on record]*`, or the
skip counts look wrong, see the troubleshooting section in
[`docs/design-notes.md`](docs/design-notes.md).

## Uninstalling

Delete the skill folder. There is no daemon, no database, and no cached state to clean
up. Past output files in `<OUTPUT_FOLDER>` are yours to keep or remove.
