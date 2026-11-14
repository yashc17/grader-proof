# Every LLM call goes through one disk cache keyed by request hash

All model calls go through one client. Before sending a request, the client computes the SHA-256 of the canonical JSON of the full request: model, messages, sampling parameters, and the prompt-template version. If a response with that key exists under `cache/llm/`, the client returns it without calling the model. Otherwise it calls the model and writes the response as one JSON file named by the key.

This makes reruns free, makes interrupted batches resumable, and lets anyone regenerate the reported numbers without API access. The cache entries behind reported results are committed. Sampling uses a fixed seed where the provider supports one. Where it does not, the cache, not the seed, is what makes results reproducible.

## Consequences

Changing anything in a prompt changes the key, so old entries are never reused by mistake. Agent runs inside Harbor call models through the agent's own client, not ours, so they are not covered by this cache. Experiments resume those at the trial level instead, by skipping trials whose result file exists.
