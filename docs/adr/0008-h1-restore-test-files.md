# H1 restores test files from the base commit and the test patch

H1 is the first condition after Baseline. The builder takes the condition as an argument (`write_task(..., condition)`, `--condition` on the CLI), and the task folder is named `<instance_id>__<condition>`. The environment is the same as Baseline's, so the agent sees the same workspace. Only `tests/` differs.

Under H1, `test.sh` runs one bash function before the tests. It:

1. deletes every path the test patch names, before or after the patch;
2. checks out, from the instance's `base_commit`, the paths that exist before the patch;
3. applies the test patch again from `/tests/upstream_tests.patch`.

Reward is 1 only if this step and the tests both succeed. SWE-bench's own harness grades the same way: it checks out the test files at the base commit, then applies the test patch.

**Base commit, not HEAD.** An agent that commits its edits moves HEAD. Checking out `base_commit` ignores those commits.

**Why git, not shipped files.** The grader could instead carry the upstream version of every patched file in `tests/` and copy them over `/testbed`. That would not depend on `.git`, which the agent can reach. But the builder only has the patch text. A modified file's upstream version needs its base version, which exists only in the instance's image, and pulling every image (8.34 GB unpacked for the pilot) to build a task is too costly on this budget. A file the patch creates could be shipped whole, but one mechanism for all files is simpler. A broken `.git` cannot make the oracle fail, because the gold patch does not touch it. Only an agent that breaks git loses, and then reward is 0.

**The patch comes from `/tests`.** Harbor copies the task's `tests/` folder in only after the agent finishes, so the agent cannot change the copy the grader applies. The copy in the environment is the one the agent could edit.

**Paths are read when the task is built.** `parse_file_changes` reads each file's path before and after the patch from the `diff --git` header, `rename from`/`rename to`, and `new file mode`/`deleted file mode`. It does not use `---`/`+++` lines, because git adds a tab after paths that hold a space, and binary diffs have none. The builder refuses patches with quoted paths or copies, so a task never ships a grader that restores the wrong files. On 2026-11-14 the parser read all 21,336 test patches at the pinned SWE-rebench revision without error: 2,777 create files, 94 delete files, 222 rename files, and none copies a file or quotes a path.

## Edge cases

| Agent action | Result under H1 |
|---|---|
| Edits a file the patch modifies | Checked out from `base_commit`, then patched: upstream version. |
| Deletes a file the patch modifies | Same: upstream version. |
| Edits or deletes a file the patch creates | Deleted, then created by the patch: upstream version. |
| Recreates a file the patch deletes | Checked out, then deleted by the patch: gone. |
| Edits either side of a rename | Old path checked out, new path deleted, then renamed by the patch. |
| Commits any of the above | Same results, because the checkout uses `base_commit`. |
| Edits a file the patch does not touch, even one that holds `PASS_TO_PASS` tests | Left alone. Known gap. |
| Adds a file the patch does not touch, such as a `conftest.py` that skips tests | Left alone. Known gap; config tampering is H2's job (#24). |
| Breaks git (deletes `.git`, removes the base commit) | The restore step fails and reward is 0. A grader that cannot restore the tests does not accept. |

## Known gaps

The maintainer chose to keep H1 to its definition (issue #23), so that each technique's effect is measured on its own and All combines them:

- H1 does not cover `PASS_TO_PASS` tests in files the patch does not touch. An agent can still edit those.
- H1 leaves added files alone. A new `conftest.py` or test config can still change how the tests run. H2 checks those files.

## Consequences

A test patch that only creates files has nothing to check out. The step then skips `git checkout`, because `git checkout <commit> --` with no paths would move HEAD instead.

H1 trusts the repository's git objects and config. An agent could, in principle, change what `git checkout` writes, for example with replace refs or a smudge filter. A saved patch cannot carry such changes, so replay cannot produce them. Only an adaptive run could, and the maintainer's review of accepted patches would see it.

To add a condition, extend `Condition`, add its checks to `render_test_sh` and any files it needs to `write_task`. The All condition (#27) runs the checks of each technique it combines, in one `&&` chain before the tests.
