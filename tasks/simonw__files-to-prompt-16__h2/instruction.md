Add `--xml` flag to structure output for Claude's long context window
# Add `--xml` flag to structure output for Claude's long context window

## Background

Anthropic has provided [specific guidelines](https://docs.anthropic.com/claude/docs/long-context-window-tips) for optimally structuring prompts to take advantage of Claude's extended context window (up to 200K tokens for Claude 3 models).

In particular, they recommend wrapping long input documents in XML tags to clearly delineate the boundaries between the documents and the rest of the prompt. This allows Claude to more accurately process the information.

## Proposal

To better support using files-to-prompt output with Claude, a new `--xml` flag should be added. When this flag is set, the tool should structure its output like this:

```xml
Here are some documents for you to reference for your task:

<documents>
<document path="path/to/file1.txt">
Contents of file1.txt
</document>

<document path="path/to/file2.txt">
Contents of file2.txt
</document>
</documents>
```

The `<documents>` and `<document>` tags clearly separate the file contents from any additional prompt text that may be provided after.

## Additional Considerations

- The `--xml` flag should be optional, preserving the default untagged output for other use as needed
- Documentation and usage examples should be updated to cover the new `--xml` option
- The XML tag output feature should be covered by new unit tests
