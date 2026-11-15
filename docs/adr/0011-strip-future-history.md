# Every condition strips future git history from the task image

SWE-rebench images are full clones. In `swerebench/sweb.eval.x86_64.12rambau_1776_sepal_ui-411`, HEAD is the base commit, but `/testbed/.git` keeps 116 refs and 1,677 commits that are not ancestors of the base commit. `git log --all -S` finds the fix and the upstream test commit (ADR 0010, known gaps). Without a fix, an agent under any condition can read the answer.

## Decision

The task builder's Dockerfile runs one step after it applies the test patch, for every condition. It keeps the branch HEAD points to and removes:

- every other ref: remote branches, tags, `refs/stash`, notes (`git update-ref --stdin`, which also rewrites `packed-refs`);
- every remote, so the agent cannot fetch the history back (`git remote remove`);
- `FETCH_HEAD`, `ORIG_HEAD` and `refs/original`;
- the reflog (`git reflog expire --expire=now --expire-unreachable=now --all`);
- the objects that only those refs reached (`git gc --prune=now`).

The base commit and its ancestors stay. H1 restores files from `base_commit`, H2 builds its reference index from `base_commit`, and H3 applies a patch on the working tree, so none of them need more.

The check is `git rev-list --all --not <base_commit>`, which must print nothing. The toy suite runs it on the image built for each condition. The toy repo's Dockerfile plants a later commit, a remote ref and a tag, so the check fails without the step.

## Why Baseline gets it too

Baseline is weak on purpose, and only in one way: the upstream tests sit in the agent's workspace (ADR 0006). It is not meant to also hand over the gold patch. If Baseline kept the future history, an exploit rate gap between Baseline and a hardened condition could come from agents that read the answer, not from the grader. All four conditions share the step, so only the grader differs.

## What it does not cover

An agent with network access can still clone the repository from GitHub. The task's network policy is Harbor's, and the same is true of the original trajectories. The step removes the copy that is already in the image, because that copy needs no effort to find.

## How often agents used the leak

`make history-reads` counts the trajectories in the dataset whose commands read history beyond HEAD, by `resolved`. It writes `results/history_reads.json`. The counts are in the PR for #56.
