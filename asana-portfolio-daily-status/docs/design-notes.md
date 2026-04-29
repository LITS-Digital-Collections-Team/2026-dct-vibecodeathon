# Design notes

A short field guide to the choices made in this skill, in case you want to fork it for
a different shape of report.

## Why "task-level comments" rather than the project status update

Asana exposes two parallel notions of "what's happening on this project":

1. **Project-level status updates** — the structured "On Track / At Risk / Off Track"
   posts you make from the project header. Returned as `current_status` on the project
   resource.
2. **Task-level comments (stories)** — the free-form notes a team adds to individual
   tasks as the work moves along. Returned as `comments` on each task resource.

In practice, most working teams keep their actual progress notes on tasks, not on the
project header. Project-level status updates tend to be either stale or written for a
non-team audience (a director, a steering committee). Pulling the latest task comment
gives a digest that reflects what was actually said yesterday.

The fallback chain still uses the project-level status if no task comments exist —
that handles brand-new projects, archived-but-still-active projects, and any project
whose team prefers the structured update form.

## Why "top 5 most-recently-modified tasks" rather than every task

Asana's API doesn't expose a "give me the most recent comment on this project"
endpoint. The closest path is:

1. List tasks for a project.
2. Sort by `modified_at` descending.
3. Inspect each task's comments and find the most recent.

A project may easily have 50–500 tasks, so iterating all of them every morning across
every project is wasteful. The "top 5 modified tasks" heuristic catches the recently
active work in essentially every realistic case. If your portfolio has a project where
real progress notes are landing on a task that hasn't otherwise been touched in months,
bump that to 10 — the algorithm is identical.

The "top 1" version of this heuristic looks tempting and was tried first; it failed
often enough that the cost of a second `get_task` call was clearly worth it. Tasks
get their `modified_at` bumped by a lot of system events (a checkbox toggle, an
assignee change, a due-date edit) that don't add a comment.

## Why `comment_limit = 50`

The Asana MCP defaults `comment_limit` to 10, and it returns the **oldest** 10
comments. On a chatty task with hundreds of comments, the default will hide every
recent comment and surface only the original kickoff conversation. Bumping to 50 is
conservative — it covers practically every active task without blowing up the response
size. Push higher only if you have unusually verbose tasks.

## Why "last item in the array" rather than the first

This trips people up: the MCP returns comments in chronological order, oldest first.
"The most recent comment" is therefore `comments[-1]` after filtering for
`type == "comment"`. Always sort by `created_at` after collecting candidates from
multiple tasks — never assume the per-task order.

## Why local-only file output

Many institutional Google Workspaces (and other corporate identity providers) block
third-party Drive API apps via domain policy. Even with a perfectly configured Drive
MCP, those calls return a generic "internal error" or a 403 deep inside a token
exchange, with no actionable feedback. Sidestepping the whole Drive API by writing
locally and letting the user's first-party sync client (Google Drive for Desktop,
Dropbox, OneDrive, etc.) handle replication is more reliable, more transparent, and
doesn't require any extra OAuth flow.

It also means the workflow degrades gracefully — if the network is down, the file
still gets written, and your sync client picks it up later.

## Why a YAML-front-matter Markdown skill rather than a Python script

The skill is small enough that a script wouldn't be much shorter, and a script would
have to handle:

- OAuth refresh against the Asana token,
- pagination plumbing,
- HTTP error retries,
- a separate scheduler (`cron`, `launchd`, `systemd timers`),
- secret storage.

The MCP-based skill outsources every one of those to infrastructure the user already
has running for other agent work. The cost is that the agent's interpretation of the
instructions has to be reliable enough day to day; the steps are written tightly so
that variance between runs is minimal.

If you'd rather write this as a script, the algorithm is small:

```python
import asana

client = asana.Client.access_token(TOKEN)
projects = client.portfolios.get_items(PORTFOLIO_GID, opt_fields=...)
# filter, then for each:
tasks = client.tasks.find_by_project(p["gid"], opt_fields="modified_at,name")
# sort, top 5, then for each:
stories = client.stories.find_by_task(t["gid"])
# filter type == "comment", take last by created_at
```

…plus the formatting block.

## Troubleshooting

- **Skip counts look wrong.** The custom-field comparison is case-insensitive and
  whitespace-trimmed against `display_value`. Check for stray whitespace in the field
  values themselves (a leading space on `"Underway "` will not match `"Underway"`).
- **Every project shows "From project status" or "No recent activity".** Most likely
  the Asana MCP is returning an empty `comments` array. Make sure
  `include_comments = true` is set in your `get_task` call, and that
  `comment_limit = 50` (not the default 10).
- **The output is empty.** Confirm the portfolio GID. The skill cannot tell the
  difference between "portfolio is empty" and "GID is wrong" — both produce zero
  items.
- **Responsible person is missing on most projects.** The custom-field name in
  `<RESPONSIBLE_FIELD>` is matched literally. Double-check capitalization and spacing
  against the field's name in Asana.
- **The agent stops with "output folder not found".** This is by design — see the
  design rationale above. Create the folder manually.
