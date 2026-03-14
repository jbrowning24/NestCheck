---
description: Push changes to a preview branch and open a PR for visual verification
---

Create a new branch named preview/<short-description-of-change>.
Stage and commit all changes with a descriptive message prefixed with the relevant NES ticket number.
Push the branch and open a PR using `gh pr create --fill`.

After the PR is created, print:

"⏳ Railway is building your preview environment. Check the PR in ~2 minutes for the preview URL."

Then print the GitHub PR URL.

Do NOT merge the PR.
