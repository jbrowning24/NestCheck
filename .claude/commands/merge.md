---
description: Merge the open PR for the current branch and return to main
---

Find the open PR for the current branch using `gh pr view --json number,url`.

If no open PR exists, say so and stop.

If a PR exists, merge it:
gh pr merge --squash --delete-branch

Then return to main:
git checkout main
git pull

Print: "✅ Merged and back on main. Ready for next task."
