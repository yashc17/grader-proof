# Trajectory fixtures

Real rows from `nebius/SWE-rebench-openhands-trajectories` at the revision pinned in
`src/grader_proof/data_facts.py`, cut down by `cut_fixtures.py` (rerun it to regenerate them).

| File | `trajectory_id` | `instance_id` | Why it is here |
|---|---|---|---|
| `normal.json` | `chatcmpl-c33f1601bba35694576802a0abf4c6f9` | `awisu2__imagenatepy-3` | Exits with `submit`. Unresolved. |
| `turn_limit.json` | `chatcmpl-e8b25f7cae5752d91fe74bc287ceeb4a` | `NCAS-CMS__cfdm-114` | Exit status `RuntimeError: Agent reached max iteration`. Unresolved. |
| `malformed_tool_call.json` | `chatcmpl-386ccb65c6811952b58fde415528875b` | `peterbe__hashin-109` | Message 30 is a tool call typed as plain text (`<tool_call><parameter=command>...`), so it never ran. Resolved. |
| `install_failed.json` | `chatcmpl-e4ed5a429bff8c829d9404b29408ea97` | `radiasoft__pykern-*` | `pip install -e .` fails to build and no test run passes afterwards. Unresolved. |
| `no_network.json` | `chatcmpl-f414c5b4f5a4d7ed46ecf14a3b8dec9c` | `conda-forge__conda-smithy-*` | `pip install` finds no versions (no network), but tests pass afterwards. The tests cut it off before that. Unresolved. |
| `import_error.json` | `chatcmpl-a7e404e12f732d7c261f7ad4ce481b12` | `pandas-dev__pandas-*` | `pandas._libs.pandas_parser` is missing in the first and in the last test run. Unresolved. |

What is cut:

- The `tools` column is dropped.
- Only two windows of messages are kept: the first 6 and a later window ending near the end. The kept ranges are in `cut_fixtures.py`. `full_message_count` records the original length.
- Message text is cut to 500 characters. For the last three fixtures, tool observations keep their first third and their tail instead, because the exit code and error are at the end. String values inside tool-call arguments are cut to 300 characters. The arguments stay valid JSON.
- `model_patch` and the metadata columns are unchanged.

No row in the 67,074 has tool-call arguments that fail to parse as JSON (checked 2026-11-14), so the
malformed fixture is the text-typed tool call. The parser still keeps unparsable arguments as text;
`tests/test_trajectory.py` covers that with a hand-built message.
