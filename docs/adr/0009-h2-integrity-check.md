# H2 rejects changed test and config files

H2 gives reward 0 if the agent changed, deleted or created a protected file. Like H1 ([ADR 0008](0008-h1-restore-test-files.md)), the environment is the same as Baseline's and only `tests/` differs: `test.sh` runs one bash function, `check_test_integrity`, before the tests, and ships a copy of the test patch in `tests/upstream_tests.patch`.

## What is protected

The list is in one place, at the top of `src/grader_proof/task_builder.py`:

- **Test config** (`PROTECTED_CONFIG`): every file named `conftest.py`, `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `setup.cfg`, `tox.ini`, `pyproject.toml`, `sitecustomize.py` or `usercustomize.py`, at any depth in the repository. Changing, deleting or creating one gives reward 0. The issue named six of these; pytest also reads `.pytest.ini` and, from pytest 9, `pytest.toml` and `.pytest.toml`, and Python runs `usercustomize.py` the same way as `sitecustomize.py`.
- **Test files** (`protected_test_files`): every path the test patch touches, before or after the patch, and every file a `FAIL_TO_PASS` or `PASS_TO_PASS` id names whose name matches pytest's default `test_*.py` or `*_test.py` (`TEST_FILE_PATTERNS`). Changing, deleting or creating one gives reward 0.
- **Test folders** (`TEST_DIRS`): every file that already exists inside a folder named `test` or `tests`, at any depth. Changing or deleting one gives reward 0.
- **New code in test folders** (`CODE_SUFFIXES`): a new file in a test folder that Python could import (`.py`, `.pyc`, `.so`) gives reward 0, unless it is named like a test file (`test_*.py`, `*_test.py`) or sits in `__pycache__`. Other new files, such as data files, are allowed.

Why these test files and not others:

- The test ids close the gap H1 leaves: 278 of the 21,336 SWE-rebench instances have test ids in files the test patch does not touch.
- Test folders cover what the listed tests import or read that is not a test file: `tests/__init__.py`, helper modules, fixture data. Only 12 gold patches change such a file (below), so the extra cover is almost free.
- New test files are allowed. The grader runs only the listed test ids, so pytest never imports a test file the agent added. Rejecting one would only punish agents that write their own tests. `__pycache__` is skipped because pytest writes bytecode there whenever the agent runs the tests.
- Other new code in a test folder is rejected because it can shadow the code under test. In pytest's default import mode, a test file's folder goes first on `sys.path`. In the toy repo, a new package `tests/toy/` with a correct `clamp` makes all three tests pass while `toy/clamp.py` stays broken (`tests/toy/patches/shadow.patch`). `.pyc` and `.so` count too, because Python imports a bare `.pyc` or an extension module placed in a folder.
- Test ids in files with other names are doctests in source modules (`pkg/mod.py::pkg.mod.func`). Those files are the code the agent must fix, so they are left out. 24 gold patches edit one.

## Where the reference comes from

The reference is the base commit with the test patch applied, computed at grading time. The function:

1. reads `base_commit`'s tree into a throwaway index (`GIT_INDEX_FILE` in a fresh temp folder);
2. applies `/tests/upstream_tests.patch` to that index (`git apply --cached`);
3. fails if `git diff` finds a protected file, or a file in a test folder, that differs from the index or is missing;
4. fails if `git ls-files --others` lists a protected config or test file that the index lacks;
5. fails if `git ls-files --others` lists new code in a test folder. This is a separate call, because its excludes (test file names, `__pycache__`) would otherwise also hide a recreated protected test file.

`git diff` compares content, so an agent commit does not hide an edit. Step 4 lists untracked files without ignore rules, so a `.gitignore` cannot hide a new `conftest.py`. The function runs in a subshell, so the repository's own index and environment are left as the agent left them.

**Why not hashes stored in the image.** The Dockerfile could hash the files after applying the test patch. But the agent runs as root in the same container and could rewrite the stored hashes. The grader can only trust what arrives in `/tests` after the agent finishes, and the builder cannot hash the files into `tests/` because it does not have the image's files (ADR 0008: pulling every image to build a task costs too much).

**Why git is enough.** A commit id names its tree by content, so the agent cannot change what `base_commit` holds without changing its id. The function sets `GIT_NO_REPLACE_OBJECTS=1` so replace refs cannot swap it either. If git is broken, the function fails and reward is 0. Like H1, H2 trusts the object store: an agent that rewrites object files or adds a clean filter in `.git/config` could fool `git diff`. A saved patch cannot carry such changes, so replay cannot produce them; only an adaptive run could, and the maintainer's review of accepted patches would see it.

**Cost.** One `read-tree`, one `git diff` limited to the protected paths and test folders, and one walk over untracked files. No other file's content is read.

## Gold patches that touch a protected file

A correct fix sometimes edits `pyproject.toml`, `setup.cfg` or `tox.ini`, for example to add a dependency. H2 then rejects it, which is a false negative. `make h2-gold-patches` counts these over the pinned SWE-rebench revision and writes `results/h2_gold_patches.json`. On 2026-11-14:

| Gold patches H2 rejects | All 21,336 instances | 6,306 instances with trajectories |
|---|---|---|
| any rule | 1,210 (5.7%) | 198 (3.1%) |
| touches a protected config file | 1,198 | 196 |
| touches a protected test file | 0 | 0 |
| changes a file already in a test folder | 12 | 1 |
| adds new code to a test folder | 5 | 1 |

2 gold patches (1 with trajectories) cannot be parsed and are not counted. Almost all config hits are in `pyproject.toml`, `tox.ini` or `setup.cfg`; one gold patch touches `conftest.py` and one `sitecustomize.py`. Most of these edits change dependencies, versions, lint settings or tox environments, not pytest settings.

H2 compares whole files and reports this cost. Comparing only the pytest sections of `pyproject.toml`, `setup.cfg` and `tox.ini` would cut the false negatives to about 0.4% (81 instances, a heuristic count), but the grader would have to parse config files, and more grader code is more ways to be wrong.

## Order inside All

H2 runs before H1. H1's restore rewrites the test files, which would hide the edits H2 looks for. `render_test_sh` adds checks to `checks` in that order.

## Edge cases

| Agent action | Result under H2 |
|---|---|
| Edits, deletes or commits a change to a file the test patch touches | Reward 0. |
| Recreates a file the test patch deletes or renames away | Reward 0. |
| Edits a test file a `PASS_TO_PASS` id names, outside the test patch | Reward 0. |
| Edits, deletes or creates a protected config file anywhere, even git-ignored | Reward 0. |
| Edits or deletes any file already in a `test` or `tests` folder, such as `tests/helpers.py` | Reward 0. |
| Adds a module or package to a test folder, such as `tests/toy/clamp.py` | Reward 0. |
| Edits code, including a module with doctest ids | Allowed. |
| Adds its own test file (`test_*.py`, `*_test.py`) or a data file to a test folder | Allowed; the grader does not run it. |
| Breaks git | The check fails and reward is 0. |

## Known gaps

- H2 checks only the repository. The agent is root and could change things outside `/testbed`: install a pytest plugin, drop a `.pth` file into site-packages, replace the installed pytest, or edit the conda `activate` script that `test.sh` sources. Neither H1 nor H2 covers this, and it is left out on purpose. A saved patch is a diff of the repository, so replay cannot carry these changes; only an adaptive run could, and the maintainer's review of accepted patches would see it.
- Shadowing from outside test folders is not caught. pytest puts the first folder above a test file that has no `__init__.py` on `sys.path`. If `tests/` is a package, that is the repository root, and in a repository whose code lives in `src/`, a new module at the root, such as `pkg.py`, hides the installed `src/pkg` (checked with pytest 8 on a small repository). Blocking every new module would reject ordinary fixes that add files.
- A new file named like a test file can still be imported if the code under test imports a module of that name. No such case is known.
- Test helpers outside a `test` or `tests` folder are protected only if the test patch touches them.
