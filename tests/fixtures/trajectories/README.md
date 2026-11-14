# Trajectory fixtures

Real rows from `nebius/SWE-rebench-openhands-trajectories` at the revision pinned in
`src/grader_proof/data_facts.py`, cut down by `cut_fixtures.py` (rerun it to regenerate them).

| File | `trajectory_id` | `instance_id` | Why it is here |
|---|---|---|---|
| `normal.json` | `chatcmpl-c33f1601bba35694576802a0abf4c6f9` | `awisu2__imagenatepy-3` | Exits with `submit`. Unresolved. |
| `turn_limit.json` | `chatcmpl-e8b25f7cae5752d91fe74bc287ceeb4a` | `NCAS-CMS__cfdm-114` | Exit status `RuntimeError: Agent reached max iteration`. Unresolved. |
| `malformed_tool_call.json` | `chatcmpl-386ccb65c6811952b58fde415528875b` | `peterbe__hashin-109` | Message 30 is a tool call typed as plain text (`<tool_call><parameter=command>...`), so it never ran. Resolved. |

What is cut:

- The `tools` column is dropped.
- Only two windows of messages are kept: the first 6 and a later window ending near the end. The kept ranges are in `cut_fixtures.py`. `full_message_count` records the original length.
- Message text is cut to 500 characters. String values inside tool-call arguments are cut to 300 characters. The arguments stay valid JSON.
- `model_patch` and the metadata columns are unchanged.

No row in the 67,074 has tool-call arguments that fail to parse as JSON (checked 2026-11-14), so the
malformed fixture is the text-typed tool call. The parser still keeps unparsable arguments as text;
`tests/test_trajectory.py` covers that with a hand-built message.
