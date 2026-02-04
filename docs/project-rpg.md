# Project RPG (H10 → RPGops)

Project:
- https://github.com/users/biohazardfish/projects/3/
- PROJECT_NUMBER=3

Required Project fields (exact names):
- Status (must include option "Todo")
- Start Date
- Target Date

Required H10 repo config:
- Secret: PROJECT_TOKEN (fine-grained PAT)
- Vars: PROJECT_OWNER=biohazardfish, PROJECT_NUMBER=3

Usage:
- Add label `quest` to an issue or PR in H10.
- The workflow adds it to RPGops and sets Status=Todo, Start Date=today, Target Date=today+14 (UTC).

Troubleshooting:
- Label must be exactly `quest`.
- Missing PROJECT_TOKEN or vars => auth/lookup failure.
- Field names/options mismatch => GraphQL lookup failure.
- Check Actions run logs for details.

TODO: Add PROJECT_TOKEN secret in GitHub UI (Settings → Secrets and variables → Actions).
