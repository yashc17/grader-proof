"""H3: holds some FAIL_TO_PASS tests out of the agent's workspace (ADR 0010).

The test patch is cut in two. The visible patch is the test patch without the held-out test
functions; the task's Dockerfile applies it. The held-out patch adds those functions back; only
the grader has it. Both are cut from the patch text, so building a task needs no image
(ADR 0008).

A function can be held out only if the test patch adds it whole. Then leaving its lines out of the
patch gives a workspace in which the function was never written. Parametrized cases of one
function are held out together, because they share one definition.
"""

import ast
import io
import random
import re
import tokenize
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

CONTEXT = 3
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")
DEF = re.compile(r"( *)(?:async\s+)?def\s+(\w+)\s*\(")
CLASS = re.compile(r"( *)class\s+(\w+)\b")


def function_of(test_id: str) -> str:
    """The test id without its parameters: `t.py::T::test_x[a]` gives `t.py::T::test_x`."""
    return test_id.split("[", 1)[0]


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    section: str  # the text git prints after the second `@@`
    lines: tuple[str, ...]  # each starts with ' ', '+', '-' or '\'

    def new_side(self) -> list[int]:
        """Indices of the lines the file has after the patch."""
        return [i for i, line in enumerate(self.lines) if line[0] in " +"]

    def trailing_context(self) -> int:
        changes = [i for i, line in enumerate(self.lines) if line[0] in "+-"]
        return sum(line[0] == " " for line in self.lines[changes[-1] + 1 :]) if changes else 0


@dataclass(frozen=True)
class FileDiff:
    text: str
    header: tuple[str, ...]
    path: str | None  # after the patch; None if the patch deletes the file or quotes its path
    created: bool
    hunks: tuple[Hunk, ...]


def parse_patch(patch: str) -> list[FileDiff]:
    sections = re.split(r"^(?=diff --git )", patch, flags=re.MULTILINE)
    return [_parse_file(section) for section in sections if section.startswith("diff --git ")]


def _parse_file(text: str) -> FileDiff:
    lines = text.removesuffix("\n").split("\n")  # not splitlines(): it also splits at "\r"
    first_hunk = next((i for i, line in enumerate(lines) if HUNK.match(line)), len(lines))
    header = tuple(lines[:first_hunk])
    target = next((line[4:] for line in header if line.startswith("+++ ")), "")
    renamed_to = next((line[10:] for line in header if line.startswith("rename to ")), None)
    path = target[2:].removesuffix("\t") if target.startswith("b/") else renamed_to
    created = any(line.startswith("new file mode ") for line in header)
    return FileDiff(text, header, path, created, tuple(_parse_hunks(lines[first_hunk:])))


def _parse_hunks(lines: list[str]) -> Iterable[Hunk]:
    """Reads hunks by their line counts, so content lines are never mistaken for headers."""
    i = 0
    while i < len(lines):
        match = HUNK.match(lines[i])
        if not match:
            raise ValueError(f"expected a hunk header, got: {lines[i]}")
        old_start, old_len, new_start, new_len, section = match.groups()
        old_left = 1 if old_len is None else int(old_len)
        new_left = 1 if new_len is None else int(new_len)
        body: list[str] = []
        i += 1
        while old_left or new_left or (i < len(lines) and lines[i].startswith("\\")):
            if i == len(lines):
                raise ValueError("the patch ends inside a hunk")
            line = lines[i] or " "  # a context line whose trailing space was stripped
            body.append(line)
            old_left -= line[0] in " -"
            new_left -= line[0] in " +"
            i += 1
        yield Hunk(int(old_start), _count(body, " -"), int(new_start), section, tuple(body))


def _count(lines: Iterable[str], kinds: str) -> int:
    return sum(line[0] in kinds for line in lines)


class Block(NamedTuple):
    """The lines of one held-out function: indices into one hunk's lines."""

    file: int
    hunk: int
    lines: frozenset[int]
    name: str


def find_function(files: Sequence[FileDiff], function: str) -> Block:
    """Locates a test function that the patch adds whole. Raises ValueError otherwise."""
    path, *names = function.split("::")
    *classes, name = names
    found = [
        (f, h, k)
        for f, diff in enumerate(files)
        if diff.path == path
        for h, hunk in enumerate(diff.hunks)
        for k in _definitions(hunk, classes, name)
    ]
    if len(found) != 1:
        raise ValueError(f"{function} is not added whole by the test patch (found {len(found)})")
    f, h, k = found[0]
    hunk = files[f].hunks[h]
    new = hunk.new_side()
    first, last = _extent(hunk, k, files[f].created)
    while first > 0 and hunk.lines[new[first - 1]] == "+":
        first -= 1  # blank lines added before the function go with it, so no gap is left
    lines = [new[i] for i in range(first, last + 1)]
    if any(hunk.lines[i][0] != "+" for i in lines):
        raise ValueError(f"{function} is not added whole by the test patch")
    if lines[-1] + 1 < len(hunk.lines) and hunk.lines[lines[-1] + 1].startswith("\\"):
        raise ValueError(f"{function} ends the file without a newline")
    return Block(f, h, frozenset(lines), name)


def _definitions(hunk: Hunk, classes: list[str], name: str) -> Iterable[int]:
    """Positions, among the hunk's new-side lines, of `def name` inside exactly `classes`."""
    text = [hunk.lines[i][1:] for i in hunk.new_side()]
    for k, line in enumerate(text):
        match = DEF.match(line)
        in_classes = match and _enclosing_classes(text[:k], len(match[1]), hunk.section)
        if match and match[2] == name and in_classes == classes:
            yield k


def _enclosing_classes(before: list[str], indent: int, section: str) -> list[str] | None:
    """Class names around a line at `indent`, read upward; None if it is not in a class body.

    When the hunk does not show the outermost class, git's hunk header usually does: it names
    the last line before the hunk that starts in column 0.
    """
    classes: list[str] = []
    for line in reversed(before):
        if line.strip() and _indent(line) < indent:
            match = CLASS.match(line)
            if not match:
                return None
            classes.insert(0, match[2])
            indent = _indent(line)
            if indent == 0:
                return classes
    if indent == 0:
        return classes
    match = CLASS.match(section.strip())
    return [match[2], *classes] if match else None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _extent(hunk: Hunk, k: int, created: bool) -> tuple[int, int]:
    """First and last new-side line of the function defined at new-side line k.

    Decorators are read upward from the `def`; the body is read with Python's tokenizer, so
    multi-line signatures and strings indented less than the body are handled.
    """
    text = [hunk.lines[i][1:] for i in hunk.new_side()]
    indent = _indent(text[k])
    first = k
    for j in range(k - 1, -1, -1):
        line = text[j]
        if not line.strip() or _indent(line) < indent:
            break
        if _indent(line) == indent:
            if line.lstrip().startswith("@"):
                first = j
            elif line.lstrip()[0] not in ")]}":
                break

    last = k + _body_length(text[k:], indent) - 1
    if not any(line.strip() for line in text[last + 1 :]):
        at_end_of_file = created or hunk.trailing_context() < CONTEXT
        if not at_end_of_file:
            raise ValueError("the function may continue past the hunk")

    block = "\n".join(_dedent(line, indent) for line in text[first : last + 1])
    try:
        tree = _parse(block)
    except SyntaxError as error:
        raise ValueError(f"cannot read the function: {error}") from error
    if not (
        len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef | ast.AsyncFunctionDef)
    ):
        raise ValueError("the lines found are not one function")
    return first, last


def _parse(source: str) -> ast.Module:
    """ast.parse without the warnings test code can raise, such as invalid escape sequences."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source)


def _dedent(line: str, indent: int) -> str:
    return line[indent:] if not line[:indent].strip() else line.lstrip()


def _body_length(lines: list[str], indent: int) -> int:
    """How many of `lines`, starting with a `def`, belong to that function, up to its last
    statement. Trailing blank and comment lines are left out."""
    source = io.StringIO("".join(_dedent(line, indent) + "\n" for line in lines))
    depth = 0
    last_row = 1
    seen_def_end = False
    try:
        for token in tokenize.generate_tokens(source.readline):
            if token.type == tokenize.INDENT:
                depth += 1
            elif token.type == tokenize.DEDENT:
                depth -= 1
                if depth == 0:
                    break
            elif token.type == tokenize.NEWLINE:
                last_row = token.start[0]
                seen_def_end = True
            elif token.type not in (tokenize.NL, tokenize.COMMENT) and depth == 0 and seen_def_end:
                break  # a one-line function, followed by the next statement
    except (tokenize.TokenError, IndentationError) as error:
        raise ValueError(f"cannot read the function: {error}") from error
    return last_row


def check_hideable(files: Sequence[FileDiff], blocks: Iterable[Block]) -> None:
    """Raises ValueError if leaving all `blocks` out would break the visible test files."""
    for f, diff in enumerate(files):
        file_blocks = [b for b in blocks if b.file == f]
        if not file_blocks:
            continue
        views = [_view(hunk, _removed(file_blocks, f, h)) for h, hunk in enumerate(diff.hunks)]
        kept = [line for view in views for line, is_kept in view if is_kept]
        for block in file_blocks:
            if any(_uses(line, block.name) for line in kept):
                raise ValueError(f"{block.name} is used elsewhere in the test patch")
        for view in views:
            _check_no_empty_body(view)
        if diff.created:
            _check_parses([line for view in views for line, _ in view], kept)


def _uses(line: str, name: str) -> bool:
    """Whether a line names `name` other than by defining a function of that name."""
    definition = DEF.match(line)
    return (
        not (definition and definition[2] == name) and re.search(rf"\b{name}\b", line) is not None
    )


def _view(hunk: Hunk, removed: set[int]) -> list[tuple[str, bool]]:
    """The hunk's lines after the patch, each with whether the visible patch keeps it."""
    return [(hunk.lines[i][1:], i not in removed) for i in hunk.new_side()]


def _check_no_empty_body(view: list[tuple[str, bool]]) -> None:
    """A class whose body was only held-out functions would be a syntax error."""
    for i, (_, is_kept) in enumerate(view):
        if is_kept or (i > 0 and not view[i - 1][1]):
            continue  # only the first line of each held-out run
        before = [line for line, k in view[:i] if k and line.strip()]
        after = next((line for line, k in view[i:] if k and line.strip()), None)
        if before and before[-1].rstrip().endswith(":"):
            opener = before[-1]
            if after is None or _indent(after) <= _indent(opener):
                raise ValueError(f"holding out would leave an empty block: {opener.strip()}")


def _check_parses(full: list[str], visible: list[str]) -> None:
    try:
        _parse("\n".join(full))
    except SyntaxError:
        return  # the upstream file does not parse with this Python; nothing to compare against
    try:
        _parse("\n".join(visible))
    except SyntaxError as error:
        raise ValueError(f"the visible test file would not parse: {error}") from error


def hide(test_patch: str, functions: Iterable[str]) -> tuple[str, str]:
    """Cuts the test patch into (visible patch, held-out patch) for the given test functions."""
    files = parse_patch(test_patch)
    return _cut(files, [find_function(files, function) for function in functions])


def _cut(files: Sequence[FileDiff], blocks: Sequence[Block]) -> tuple[str, str]:
    check_hideable(files, blocks)
    visible = _visible_patch(files, blocks)
    if not visible:
        # The task's Dockerfile applies the visible patch, and `git apply` rejects an empty one.
        raise ValueError("holding out would leave the visible patch empty")
    return visible, _held_out_patch(files, blocks)


def _removed(blocks: Iterable[Block], f: int, h: int) -> set[int]:
    return {i for b in blocks if (b.file, b.hunk) == (f, h) for i in b.lines}


def _visible_hunks(diff: FileDiff, removed: list[set[int]]) -> list[str]:
    """The diff's hunks without the held-out lines. Hunks left with no change are dropped."""
    out: list[str] = []
    shift = 0
    for hunk, gone in zip(diff.hunks, removed, strict=True):
        lines = [line for i, line in enumerate(hunk.lines) if i not in gone]
        if _count(lines, "+-"):
            new_len = _count(lines, " +")
            header = f"@@ -{hunk.old_start},{hunk.old_len} +{hunk.new_start - shift},{new_len} @@"
            out.append(header + hunk.section + "\n")
            out.extend(line + "\n" for line in lines)
        shift += len(gone)
    return out


def _visible_patch(files: Sequence[FileDiff], blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for f, diff in enumerate(files):
        removed = [_removed(blocks, f, h) for h in range(len(diff.hunks))]
        if not any(removed):
            out.append(diff.text)
        elif hunks := _visible_hunks(diff, removed):
            out.extend(line + "\n" for line in diff.header)
            out.extend(hunks)
        elif any(line.startswith("rename from ") for line in diff.header):
            # A rename with no change left; git rejects `---`/`+++` lines without a hunk.
            out.extend(line + "\n" for line in diff.header if not line.startswith(("---", "+++")))
        # Any other file left with no change is left out.
    return "".join(out)


def _held_out_patch(files: Sequence[FileDiff], blocks: Sequence[Block]) -> str:
    """A patch from the visible test files to the upstream ones."""
    out: list[str] = []
    for f, diff in enumerate(files):
        removed = [_removed(blocks, f, h) for h in range(len(diff.hunks))]
        if not any(removed):
            continue
        if diff.created and not _visible_hunks(diff, removed):
            out.append(diff.text)  # the visible patch does not create this file at all
            continue
        out.append(f"diff --git a/{diff.path} b/{diff.path}\n")
        target = next(line[len("+++ b/") :] for line in diff.header if line.startswith("+++ b/"))
        out.append(f"--- a/{target}\n+++ b/{target}\n")
        shift = 0
        for hunk, gone in zip(diff.hunks, removed, strict=True):
            if gone:
                out.extend(_held_out_hunks(hunk, gone, visible_start=hunk.new_start - shift))
            shift += len(gone)
    return "".join(out)


def _held_out_hunks(hunk: Hunk, removed: set[int], visible_start: int) -> Iterable[str]:
    """Rewrites one hunk as visible -> upstream: held-out lines are added, the rest is context.

    Context is cut to CONTEXT lines around each group of added lines, so an agent's edit further
    away does not stop the patch from applying.
    """
    view: list[str] = []
    for i in hunk.new_side():
        line = ("+" if i in removed else " ") + hunk.lines[i][1:]
        if i + 1 < len(hunk.lines) and hunk.lines[i + 1].startswith("\\"):
            line += "\n" + hunk.lines[i + 1]  # "\ No newline at end of file" stays with its line
        view.append(line)
    groups: list[list[int]] = []
    for i, line in enumerate(view):
        if line[0] != "+":
            continue
        if groups and i - groups[-1][-1] <= 2 * CONTEXT + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    for group in groups:
        start = max(0, group[0] - CONTEXT)
        end = min(len(view), group[-1] + CONTEXT + 1)
        old_len = _count(view[start:end], " ")
        old_start = visible_start + _count(view[:start], " ") - (old_len == 0)
        new_start = hunk.new_start + start
        yield f"@@ -{old_start},{old_len} +{new_start},{end - start} @@{hunk.section}\n"
        yield from (line + "\n" for line in view[start:end])


class HeldOut(NamedTuple):
    visible: tuple[str, ...]  # FAIL_TO_PASS ids the agent's workspace contains
    held_out: tuple[str, ...]  # FAIL_TO_PASS ids only the grader has
    visible_patch: str
    held_out_patch: str


def hold_out(instance_id: str, test_patch: str, fail_to_pass: Sequence[str]) -> HeldOut:
    """Holds out half of the FAIL_TO_PASS test functions, rounded down, so at least one stays.

    Functions are tried in an order seeded with the instance id; one that cannot be hidden is
    skipped. Raises ValueError if none can be held out.
    """
    functions = sorted({function_of(t) for t in fail_to_pass})
    files = parse_patch(test_patch)
    chosen: list[str] = []
    blocks: list[Block] = []
    cut = ("", "")
    for function in random.Random(instance_id).sample(functions, len(functions)):
        if len(chosen) == len(functions) // 2:
            break
        try:
            block = find_function(files, function)
            patches = _cut(files, [*blocks, block])
        except ValueError:
            continue
        chosen.append(function)
        blocks.append(block)
        cut = patches
    if not chosen:
        raise ValueError(f"{instance_id}: no FAIL_TO_PASS test can be held out")
    held = tuple(t for t in fail_to_pass if function_of(t) in chosen)
    visible = tuple(t for t in fail_to_pass if function_of(t) not in chosen)
    return HeldOut(visible, held, *cut)
