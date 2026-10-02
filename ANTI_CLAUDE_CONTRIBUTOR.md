# Anti-Claude Contributor Log

Date: 2026-10-02  
Author: S-k404  

---

## 1. Problem Overview
When using Claude / Claude Code to assist with development and git operations, Claude by default appends a trailer line to commit messages:
```text
Co-Authored-By: Claude <noreply@anthropic.com>
```
Because GitHub parses every commit's metadata (author email and `Co-Authored-By:` lines) to determine repository contributors, GitHub automatically credited Anthropic / Claude as a contributor on the repository page. 

Simply deleting and re-pushing from a local machine does not fix this if the underlying commits still contain the trailer or Claude email.

---

## 2. Actions Taken

### A. Repository History Resets (Option 1)
To ensure a completely clean contributor graph with 100% ownership credited to `S-k404`, the git histories of the following repositories were reset using orphan branches to a single clean "Initial commit" and force-pushed:
* **`Cloudflare-Site`** (`S-k404/portfolio`)
* **`music-tools`** (`S-k404/music-tools`)
* **`Music Visualiser`** (`S-k404/music-visualiser`)
* **`Notion-Better-Export`** (`S-k404/notion-better-export`)

Command sequence executed:
```bash
git checkout --orphan clean-main
git add -A
git commit -m "Initial commit"
git branch -D main
git branch -m main
git push -f --progress origin main
```

### B. Upstream / Fork Cleanups
* **`S-k404/odysseus` (Fork):** Stripped the `Co-Authored-By` trailer from branch `feature/notion-readonly-mcp` and force-pushed.
* **`Docker/Notoma`:** Rewrote local feature branch commits to remove all Claude trailers without disturbing uncommitted working changes.

### C. Prevention Rules (`CLAUDE.md`)
Added and verified instructions across all repositories:
```markdown
## Git commits

Do not add a `Co-Authored-By: Claude` (or any Anthropic/Claude attribution) trailer to commit messages in this repository. This overrides Claude Code's default commit-attribution behavior for this project.
```
Configured in:
* `music-tools/CLAUDE.md`
* `Music Visualiser/CLAUDE.md`
* `Docker/Notion-Better-Export/CLAUDE.md`
* `Docker/Odysseus Skill/CLAUDE.md`
* `Docker/Better-vertsh/CLAUDE.md`
* `Docker/kokoro-audiobook-studio/CLAUDE.md`
* `Docker/Notoma/CLAUDE.md`

---

## 3. Future Commit Behavior & Workflow

### Will future commits update normally?
**Yes.** 
* You do **not** need to use orphan branches or force-push (`-f`) ever again.
* Every regular commit you push (`git commit` followed by `git push`) will immediately appear on GitHub, count toward your contribution streak/calendar, and maintain your 100% sole contributor status.

### Normal day-to-day workflow:
```bash
git add .
git commit -m "Your commit message"
git push origin main
```

### Quick sanity check (optional):
To verify that a commit before pushing has no unwanted trailers:
```bash
git log -1
```
Ensure no `Co-Authored-By` lines are present.
