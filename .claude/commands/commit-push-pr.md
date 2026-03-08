Commit all staged and unstaged changes, push to the current branch, and open a pull request.

Use the following pre-computed context to avoid unnecessary tool calls:

**Git status:**
```
${{ git status }}
```

**Current branch:**
```
${{ git branch --show-current }}
```

**Recent commits on this branch:**
```
${{ git log --oneline -10 }}
```

**Diff summary:**
```
${{ git diff --stat }}
```

**Existing PR for this branch (if any):**
```
${{ gh pr view --json url,state 2>/dev/null || echo "No existing PR" }}
```

## Steps

1. Review the diff and status above. Stage all relevant changed files (avoid secrets, .env, credentials).
2. Write a concise commit message that explains the **why**, not just the what. Follow conventional commit style if the repo uses it.
3. Commit the changes.
4. Push to the current branch with `-u origin <branch>`.
5. Open a PR using `gh pr create` with:
   - A short, descriptive title (under 70 chars)
   - A body with a `## Summary` section (1-3 bullet points) and a `## Test plan` section
6. Return the PR URL.

If there is already an open PR for this branch, push and inform the user instead of creating a duplicate PR.
