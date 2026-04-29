---
name: asana-portfolio-daily-status
description: On a recurring schedule (e.g., every weekday morning), compile the most recent task-level comment for each active project in a configured Asana portfolio and save the results as a dated Markdown file in a local folder.
---

Compile the most recent task-level comment for each active project in a configured
Asana portfolio and save the result as a dated Markdown file to a local folder. The
local folder may be a vanilla directory or one that a sync client (e.g., Google Drive
for Desktop, Dropbox, OneDrive, Syncthing, rclone) mirrors elsewhere — this skill does
no remote uploads of its own.

> **Before running this skill, edit the placeholders below.** They are written in
> `<ANGLE_BRACKETS>` and listed in `CONFIGURATION.md` at the root of this package.

## Fixed identifiers (edit these)

- Asana portfolio GID: `<PORTFOLIO_GID>` (name: `<PORTFOLIO_NAME>`)
- Output folder (absolute local path): `<OUTPUT_FOLDER>`
- Output filename pattern: `<FILE_PREFIX>-Status-YYYY-MM-DD.md` (today's local date)
- Filter field: Asana custom field named `<WORKFLOW_CATEGORY_FIELD>`
  - Excluded values (case-insensitive): `<EXCLUDED_VALUE_1>`, `<EXCLUDED_VALUE_2>`, ...
    plus empty/null
  - Treat all other values as "active"
- Optional responsible-person custom field: `<RESPONSIBLE_FIELD>` (falls back to project
  owner if unset)

## Why this design

Many institutional Google Workspaces block third-party Drive API apps at the domain
policy level, which prevents most "write to Drive" MCP connectors from working. Writing
the file locally and letting a first-party sync client (Google Drive for Desktop,
Dropbox, OneDrive, etc.) mirror it sidesteps that policy entirely. The whole workflow
is local file I/O plus the Asana MCP — nothing else.

If you don't need sync at all, point `<OUTPUT_FOLDER>` at any local directory.

## Required connectors / tools

- **Asana MCP** with at least: `get_items_for_portfolio`, `get_tasks`, `get_task`
- **Local file system access** via the agent's Read/Write tools or shell

If the Asana MCP is unavailable, stop and report.

## Steps

### 1. Fetch and filter portfolio projects

Call `get_items_for_portfolio`:

- `portfolio_gid = "<PORTFOLIO_GID>"`
- `limit = 100`
- `opt_fields = "name,gid,permalink_url,current_status.text,current_status.created_at,custom_fields.name,custom_fields.display_value,owner.name"`

Paginate via `next_page.offset`. Cap at 500 items; note truncation in the summary.

For each project, find the custom field whose `name == "<WORKFLOW_CATEGORY_FIELD>"`. Skip
the project if its `display_value` (lowercased, trimmed) matches any excluded value or is
empty/null. Track per-category skip counts.

For each passing project, record:

- `name`, `gid`, `permalink_url`
- `category` — the workflow category `display_value`
- `responsible` — the `<RESPONSIBLE_FIELD>` `display_value`; fall back to `owner.name`;
  omit the parenthetical if both are empty
- `current_status_text` and `current_status_date` from `current_status` (used only as
  fallback)

Sort passing projects A–Z by name (case-insensitive).

### 2. Find the most recent task comment for each project

For each active project:

**a. Fetch tasks**

Call `get_tasks` with:

- `project = <project_gid>`
- `opt_fields = "gid,name,modified_at"`
- `limit = 100`

Paginate if needed (most projects fit in one page).

**b. Sort tasks by `modified_at` descending and take the top 5.**

**c. Fetch comments from each of those 5 tasks**

Call `get_task` for each:

- `task_id = <task_gid>`
- `include_comments = true`
- `include_subtasks = false`
- `comment_limit = 50`

Filter the `comments` array to entries where `type == "comment"`. Comments are
returned **oldest-first**, so the **last entry in the filtered array** is the most
recent comment on that task.

**d. Find the single most recent comment across all 5 tasks** by comparing
`created_at` timestamps. Record:

- `comment_text` — the `text` field
- `comment_date` — `created_at` formatted `YYYY-MM-DD`
- `comment_task` — the task `name` (internal reference; not shown in output)

**e. Clean the comment text**

- Strip Asana @mention profile URLs: remove any substring matching
  `https://app.asana.com/0/profile/[0-9]+` (with or without trailing whitespace).
- Strip any leading/trailing blank lines.

**f. Fallback chain** (if no qualifying comments are found across all 5 tasks)

1. Use `current_status_text` from the portfolio fetch, formatting the date as `Mon
   YYYY`. Render the sub-bullet as: `*[From project status, Mon YYYY] text*`
2. If `current_status_text` is also null: `*[No recent activity on record]*`

### 3. Write the Markdown file

Write to:

`<OUTPUT_FOLDER>/<FILE_PREFIX>-Status-YYYY-MM-DD.md`

Encoding: UTF-8, no BOM, LF line endings. Overwrite if the file already exists.

**Format — flat meeting-notes style:**

```
**<PORTFOLIO_DISPLAY_NAME> — Month D, YYYY**

- [Project Name](permalink_url) (Responsible Person)
  - Most recent comment text here.
- [Another Project](permalink_url) (Responsible Person) *(Stuck)*
  - Most recent comment text here.
- [No-Activity Project](permalink_url) (Responsible Person) *(Scheduled)*
  - *[No recent activity on record]*
```

Rules:

- One blank line after the bold date line; the project list follows with no blank lines
  between items.
- No `---` separators, no `#` headings, no blockquotes (`>`), no bold metadata labels.
- Project name is a Markdown hyperlink: `[Name](permalink_url)`.
- Responsible person(s) in plain parentheses on the same line as the link.
- For projects whose `category` is **not** the institution's "default in-progress" value
  (configured as `<DEFAULT_ACTIVE_CATEGORY>`), append the category in italics, e.g.,
  `*(Stuck)*`, `*(Scheduled)*`. Skip the suffix when category equals
  `<DEFAULT_ACTIVE_CATEGORY>`.
- Comment is one indented sub-bullet (`  - text`). If the comment has multiple lines,
  render each non-empty line as its own sub-bullet.
- Fallback text is italicized (see step 2f).
- Do NOT include comment author, date, or task name in the output.

If zero projects pass the filter, write only the bold date line followed by
`_No active projects today._`.

Also save a copy to the agent's session outputs directory under the same filename, for
quick access via the chat link.

### 4. Report

Concise summary, under ~10 lines:

- Total projects fetched (truncation note if any)
- Skipped: per-category counts
- Projects written: N (X with task comments · Y from project status · Z no activity)
- A `computer://` link to the local Markdown file
- A reminder line if a sync client is expected to mirror the file (e.g., "Drive for
  Desktop will sync this to the shared folder").

## Notes

- Filtering is case-insensitive and whitespace-trimmed.
- Categories you want to keep visible (like "Stuck" or "Blocked") should NOT be in the
  exclusion list — those are still active work.
- Comments are returned oldest-first by the MCP; always take the **last** item in the
  filtered array (not the first) for the most recent comment.
- `comment_limit = 50` is required. The default of 10 returns only the oldest 10
  comments and will miss any newer ones.
- Tasks can have their `modified_at` updated by non-comment system events (field
  changes, completions). Checking 5 tasks rather than 1 guards against this.
- Do NOT call any Google Drive, Sheets, or Docs MCP — local I/O only.
- Do NOT write outside `<OUTPUT_FOLDER>`.
- If `<OUTPUT_FOLDER>` does not exist, stop and report — do NOT create it. (Rationale:
  a missing folder usually signals that the sync client is not set up yet.)
