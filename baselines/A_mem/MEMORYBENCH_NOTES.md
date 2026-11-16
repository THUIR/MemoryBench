# A-Mem in MemoryBench

## Upstream snapshot

- Repository: https://github.com/WujiangXu/A-mem
- Commit: `f9a173dec325d84fcc97e7828775c7b241c33466`
- Retrieved: 2026-11-07
- Entry point: `baselines.A_mem.memory_layer.AgenticMemorySystem`
- All tracked upstream files are vendored, including its license, examples and
  evaluation data. No nested Git repository or editable installation is needed.
- The old `agiresearch/A-mem` system-library snapshot (`agentic_memory/`) has been
  replaced, not combined with the new implementation.

## Local upstream patch

The only patched upstream file is `memory_layer.py`:

1. `OpenAIController` accepts an optional `api_base` and passes it as `base_url`
   to the OpenAI SDK. `LLMController` forwards its existing `api_base` argument.
2. The SDK timeout follows `LLM_REQUEST_TIMEOUT` (default 180 seconds), matching
   MemoryBench's clients.
3. Removed the unused `from ast import Str` import, which prevents the module
   from importing on Python 3.14.
4. Analysis and evolution retry invalid JSON responses up to three total attempts
   before using the default-note or no-evolution fallback. Separate counters
   distinguish these fallbacks from other failures. Context-length handling is
   described below. `MEMORY_VERSION` is increased from upstream's `2` to `4`.
5. Completion diagnostics record the finish reason and token usage; verbose
   analysis, prompt, response, and neighbor-index prints are removed.
6. Local embedding model paths use `local_files_only=True`. Consolidation reuses
   the existing encoder and publishes the rebuilt index only after all documents
   have been embedded, avoiding a second model load or a partially rebuilt index.

Metadata prompts, embedding text formats, integer-index retrieval, link
validation, neighbor-update logic, and consolidation timing retain upstream
behavior. `refresh_index=False` retains upstream's deferred index updates. The
separate `memory_layer_robust.py` and standalone LoCoMo runners are retained as
upstream references, not used by MemoryBench.

## MemoryBench adapter

`src/agent/a_mem.py` maps both existing providers to A-Mem's `openai` backend.
For `vllm`, the endpoint is `llm_config.vllm_base_url`, then `VLLM_BASE_URL`, then
`http://localhost:8000/v1`. Credentials are `llm_config.api_key`, then
`VLLM_API_KEY`, then `EMPTY` for a server without authentication. OpenAI uses
`llm_config.openai_base_url` / `OPENAI_BASE_URL` and its normal API key.
Resolved endpoints and credentials are passed explicitly to both clients; no
process-global endpoint or key is modified. Existing `configs/memory_systems/a_mem.json`
continues to work. API keys are never written to the cache manifest.

A-Mem memory construction uses upstream sampling defaults (`temperature=0.7`,
`max_tokens=1000` for the OpenAI controller). Keyword query generation and final
answers continue through MemoryBench's existing client and configured sampling
parameters. The endpoint must support the JSON-schema Chat Completions requests
used for metadata and evolution. Check schema support and model output against
the actual endpoint before a full benchmark.

The adapter preserves `add_memory()`'s `(id, content)` return contract. Query JSON
parsing retries at most three times. After each serial write, the adapter checks
upstream failure counters: `llm_call`, `analyze`, and `evolve` failures raise and
prevent saving the failed build. JSON fallbacks and invalid links are logged but
do not prevent saving. An analysis JSON fallback stores empty keywords/tags and
the default context; an evolution JSON fallback skips that evolution step.

The current context-length handling depends on the server's error message:
HTTP 400 responses containing `maximum context length` take the JSON fallback
path immediately, without retries. Other context-length messages recognized by
`is_context_length_error`, including `maximum model length` and
`context_length_exceeded`, propagate and prevent saving. Consequently, a saved
cache does not guarantee that every note was successfully analyzed or evolved;
review fallback logs when interpreting experiment results.

The upstream metadata and integer-neighbor paths address
https://github.com/THUIR/MemoryBench/issues/10. Memory ingestion remains serial;
query prediction can be parallel.

Corpus evaluation already creates a separate solver from the base cache for
each dataset. Its temporary evolved state is discarded after evaluation. The
unused tail-deletion code was removed: deleting appended notes would not undo
changes made to earlier notes by evolution.


## Running the A-Mem experiments

From the repository root, after configuring the model servers and the benchmark
environment:

```bash
python -m src.off-policy \
  --dataset_type domain --set_name Legal \
  --memory_system a_mem \
  --memory_system_config configs/memory_systems/a_mem.json \
  --memory_cache_prefix a_mem_v2 \
  --threads 4
```