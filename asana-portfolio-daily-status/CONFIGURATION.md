# Configuration

Every site-specific value in `skill/SKILL.md` is written as `<ANGLE_BRACKETS>`. Replace
each one inline before scheduling the task. Nothing else in the skill should need to
change.

## Placeholder reference

| Placeholder                  | Required? | What it is                                                                                                       | How to find it                                                                                                                                                |
| ---------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<PORTFOLIO_GID>`            | yes       | Asana's internal numeric ID for your portfolio.                                                                  | Open the portfolio in your browser; the GID is the long number in the URL: `https://app.asana.com/0/portfolio/<GID>/list`. Or ask Claude: "What's the GID of the X portfolio?" |
| `<PORTFOLIO_NAME>`           | yes       | The exact human-readable name of the portfolio in Asana.                                                          | Copy from the portfolio header.                                                                                                                                |
| `<PORTFOLIO_DISPLAY_NAME>`   | yes       | The label that appears at the top of the daily Markdown digest. Often the same as `<PORTFOLIO_NAME>`, but you can shorten or rewrite it. | Free text.                                                                                                                                                    |
| `<OUTPUT_FOLDER>`            | yes       | Absolute local path to the folder where the dated Markdown files will be written.                                 | Pick a folder and `mkdir -p` it. If you want the file synced, point at a folder a sync client already mirrors.                                                 |
| `<FILE_PREFIX>`              | yes       | Filename prefix for the daily Markdown file. Resulting name: `<FILE_PREFIX>-Status-YYYY-MM-DD.md`.                | Free text. Avoid spaces. Examples: `MyTeam`, `DigCol`, `Engineering`.                                                                                          |
| `<WORKFLOW_CATEGORY_FIELD>`  | yes       | The exact name of the Asana custom field used to mark project state.                                              | In Asana, open any project, look at the right-side custom-fields panel; the field name must match exactly (case-insensitive comparison applies to its values, not its name). |
| `<EXCLUDED_VALUE_1>` …       | yes       | One or more values of the workflow field that should be **skipped**.                                              | Common picks: `Hold`, `Uncategorized`, `Requested`, `Archived`, `Done`. Empty/null is always skipped automatically.                                            |
| `<DEFAULT_ACTIVE_CATEGORY>`  | yes       | The "ordinary in-progress" category. When a project is in this category, no italic suffix is added to its line.    | Examples: `Underway`, `Active`, `In Progress`. Anything else (e.g., `Stuck`, `Scheduled`, `Blocked`) gets an italic `*(Category)*` suffix in the digest.       |
| `<RESPONSIBLE_FIELD>`        | optional  | Name of a custom field that holds the project's responsible person.                                                | If you don't have one, leave the placeholder; the skill falls back to the project's `owner.name`.                                                              |

## Example: filled-in values

Suppose you run a small library-systems team using Asana with a portfolio called "ILS
Modernization", and you tag projects with a custom field "Status" whose values are
`Active`, `Stuck`, `Scheduled`, `Hold`, `Done`. You'd set:

| Placeholder                  | Value                                              |
| ---------------------------- | -------------------------------------------------- |
| `<PORTFOLIO_GID>`            | `1209876543210000`                                 |
| `<PORTFOLIO_NAME>`           | `ILS Modernization`                                |
| `<PORTFOLIO_DISPLAY_NAME>`   | `ILS Modernization`                                |
| `<OUTPUT_FOLDER>`            | `/Users/jdoe/Documents/Asana Status`               |
| `<FILE_PREFIX>`              | `ILS`                                              |
| `<WORKFLOW_CATEGORY_FIELD>`  | `Status`                                           |
| Excluded values              | `Hold`, `Done`                                     |
| `<DEFAULT_ACTIVE_CATEGORY>`  | `Active`                                           |
| `<RESPONSIBLE_FIELD>`        | (omit; use project owner)                          |

The resulting daily file name would be `ILS-Status-2026-04-29.md`.

## Things people commonly miscopy

- **Custom-field name.** The skill compares against the exact `name` Asana returns
  from the API. If your field is `Workflow Status`, you can't put `Workflow_Status` in
  the placeholder — that won't match anything.
- **GID vs. permalink.** A portfolio's permalink may include other numbers; the GID is
  the long numeric ID after `/portfolio/`. When in doubt, ask Claude to look it up via
  the Asana MCP's `get_portfolios` tool.
- **Output folder doesn't exist yet.** The skill will refuse to create it for you.
  This is intentional — a missing folder usually means the sync client isn't set up.
- **Trailing slashes in `<OUTPUT_FOLDER>`.** Either form works, but stay consistent.
