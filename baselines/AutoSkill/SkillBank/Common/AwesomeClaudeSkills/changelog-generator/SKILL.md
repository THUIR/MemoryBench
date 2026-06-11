---
name: changelog-generator
description: >-
  Generates user-facing changelogs and release notes from git commit history.
  Parses conventional commits, categorizes changes into features, fixes,
  breaking changes, and more, then rewrites technical messages into
  customer-friendly language. Use when the user asks to generate a changelog,
  write release notes, summarize recent commits, prepare CHANGELOG.md, or
  document what changed between versions.
---

# Changelog Generator

Generate structured, user-facing changelogs from git commit history.

## Workflow

### Step 1 — Gather commits

Determine the commit range from the user's request, then fetch commits:

```bash
# Between tags/versions
git log v1.2.0..v1.3.0 --oneline --no-merges
# Since a date
git log --since="2024-03-01" --oneline --no-merges
# Since last tag (default when no range given)
git log "$(git describe --tags --abbrev=0)"..HEAD --oneline --no-merges
```

If there are no tags and no range specified, ask the user for a date or count.

### Step 2 — Categorize each commit

Apply these rules based on the commit message prefix:

| Prefix / pattern | Category |
|---|---|
| `feat:` `feature:` | New Features |
| `fix:` `bugfix:` | Bug Fixes |
| `perf:` | Performance |
| `BREAKING CHANGE` or `!:` suffix | Breaking Changes |
| `security:` `vuln:` | Security |
| `docs:` `test:` `ci:` `chore:` `refactor:` `style:` `build:` | Skip (internal) |

For non-conventional messages, infer category from content. Exclude purely internal commits (test infra, CI config, linting, dependency bumps with no user impact).

### Step 3 — Rewrite for a non-technical audience

Transform each kept commit into a clear, benefit-focused sentence:

- Strip scope tags like `(api):` or `(auth):`
- Expand abbreviations and jargon
- Lead with the user-visible outcome, not the implementation
- Use present tense: "Add", "Fix", "Improve"
- One sentence per entry

Example: `fix(auth): race condition in token refresh` becomes
"Fix an issue where sessions could expire unexpectedly during use."

### Step 4 — Format the output

```markdown
# Changelog — vX.Y.Z (YYYY-MM-DD)

## Breaking Changes
- [entry]

## New Features
- [entry]

## Improvements
- [entry]

## Bug Fixes
- [entry]

## Security
- [entry]
```

Omit any empty section. Order: breaking changes, features, improvements, fixes, security. If the repo already has a `CHANGELOG.md` or `CHANGELOG_STYLE.md`, match its existing conventions instead.

### Step 5 — Validate before presenting

1. Confirm no internal-only commits leaked through
2. Confirm every entry is understandable without reading source code
3. Confirm date and version label are correct
4. Write to `CHANGELOG.md` (prepend above existing content) or print inline, based on the user's request
