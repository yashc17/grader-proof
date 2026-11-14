# Zero cash budget: laptop, GitHub Actions and Tinker credit

The project spends no cash. The laptop (Apple M3, arm64) runs the x86-only SWE-rebench images through Colima with Rosetta emulation, which is fine for building and debugging one task at a time. Oracle checks and replays are deterministic, so they run on GitHub Actions, which is free for public repositories on real x86 runners. That also means anyone can rerun them from the repository. Model calls use a local 8–9B open model during development. Final judge runs, the red team and M4 use open-weight models on Tinker, paid from an existing grant, capped at $50.

## Considered options

- A rented x86 VM: simplest, but it costs money and its runs cannot be reproduced by readers.
- Laptop only: no x86 machine that others can use, and 79 GB of free disk limits how many images fit.
- Hosted sandboxes (Daytona, Modal): paid per sandbox, and harder to debug at the container level, which is exactly where M2 and M3 work.

## Consequences

Actions runners have 14 GB of disk, so each job handles one image. Agent runs stay on the laptop, so M3 and M4 run overnight and must be resumable.
