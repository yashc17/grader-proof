"""The real Tinker call. Reads TINKER_API_KEY from the environment."""

# The Hugging Face tokenizer is loosely typed, so strict checking only adds noise here.
# pyright: basic

import tinker

from grader_proof.llm import Request, Response


class TinkerTransport:
    def __init__(self) -> None:
        self._service = tinker.ServiceClient()
        self._samplers: dict[str, tinker.SamplingClient] = {}

    def _sampler(self, model: str) -> tinker.SamplingClient:
        if model not in self._samplers:
            self._samplers[model] = self._service.create_sampling_client(base_model=model)
        return self._samplers[model]

    def complete(self, request: Request) -> Response:
        sampler = self._sampler(request.model)
        tokenizer = sampler.get_tokenizer()
        prompt = str(
            tokenizer.apply_chat_template(
                list(request.messages), add_generation_prompt=True, tokenize=False
            )
        )
        prompt_ids: list[int] = tokenizer.encode(prompt, add_special_tokens=False)
        params = tinker.types.SamplingParams(
            max_tokens=request.max_tokens, temperature=request.temperature, seed=request.seed
        )
        result = sampler.sample(
            prompt=tinker.types.ModelInput.from_ints(prompt_ids),
            num_samples=1,
            sampling_params=params,
        ).result()
        tokens = list(result.sequences[0].tokens)
        return Response(
            text=str(tokenizer.decode(tokens)),
            prompt_tokens=len(prompt_ids),
            completion_tokens=len(tokens),
        )
