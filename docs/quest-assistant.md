# Quest Assistant

## What it does
When the `quest` label is added to an Issue or PR, a GitHub Action generates an Obsidian-ready template and commits it to the repo.

## Trigger rules
- Runs on `issues` and `pull_request` labeled events.
- The label must be exactly `quest`.

## Output path
- `.quest-resources/Q{number}.md`

## Non-overwrite rule
- If the file already exists, the workflow skips creation.

## How to test
1. Create a new Issue in H10.
2. Add the label `quest`.
3. Check the Actions tab for “Quest Assistant (generate Obsidian template)”.
4. Confirm the new file appears in the repo at `.quest-resources/Q{issue_number}.md`.
