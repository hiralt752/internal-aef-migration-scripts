# internal-aef-migration-scripts

## Environment Variables

### Gemini access

`GEMINI_API_KEY`
- Authenticates Gemini API requests.
- If missing or invalid, all Gemini calls fail.

`GEMINI_MODEL`
- Legacy/default Gemini model reference.
- Kept for compatibility with older scripts.

`GEMINI_FALLBACK_MODEL`
- Legacy fallback model reference.
- Kept for compatibility with older scripts.

### Runner model routing

`AI_ENGINE_PRIMARY_MODEL`
- First model used for classification.
- Default use case: send most questions to `gemini-2.5-flash-lite`.

`AI_ENGINE_FALLBACK_MODELS`
- Comma-separated fallback model list.
- Used when the primary response has invalid JSON, low confidence, missing/wrong outcome key, or other validation failure.
- Example: `gemini-2.5-flash,gemini-2.5-pro`

`AI_ENGINE_MIN_CONFIDENCE`
- Minimum accepted confidence score.
- If the response confidence is below this threshold, the runner retries on a fallback model.

`AI_ENGINE_FORCE_JSON_RESPONSE`
- Forces Gemini output to `application/json`.
- Keep this `true` for classification runs that require predefined JSON only.

`AI_ENGINE_DIRECT_FLASH_IMAGE_THRESHOLD`
- If a single-question record has at least this many images, the runner starts directly on the fallback model instead of the lite model.
- Use this when image-heavy questions are not reliable on the primary model.

`AI_ENGINE_DIRECT_FLASH_COMPLEX_PROMPT_CHARS`
- For complex math/science prompts, if prompt length meets or exceeds this number of characters, the runner starts directly on the fallback model.
- Use this to bypass the lite model for heavier reasoning cases.

### Validation and retry control

`AI_ENGINE_FAIL_SCHEMA_VALIDATION`
- Controls strictness when a parsed response fails validation.
- `false`: retry/fallback logic handles the issue and the run continues.
- `true`: validation failures are treated more aggressively for debugging or strict enforcement.

`AI_ENGINE_BATCH_INVALID_JSON_RETRIES`
- Number of batch retries allowed after invalid JSON before split/recovery logic takes over.

### Batch execution

`AI_ENGINE_BATCH_ENABLED`
- Enables grouped batch processing.
- Set `false` to process question-by-question instead.

`AI_ENGINE_BATCH_PREVIEW_ONLY`
- Generates manifests and prompt previews without making live Gemini generation calls.
- Use `true` to inspect grouping, lesson context, and prompt composition before API execution.

`AI_ENGINE_ASSEMBLED_REQUEST_PREVIEW_LIMIT`
- When preview-only mode is enabled, controls how many assembled batch request text files are written for audit.
- These files show lesson context, batch instruction, and question text exactly as assembled before Gemini generation.
- Use `0` to disable assembled request preview file generation.

### Processing limits and concurrency

`AI_ENGINE_PROCESS_LIMIT`
- Limits how many records are processed in one run.
- `0` means process all records.
- Use a small number like `5` or `10` for testing.

`AI_ENGINE_MAX_WORKERS`
- Controls concurrency.
- `1` is the safest setting for quota/rate-limited runs.
- Increase only if API capacity allows parallel execution.

## Common Run Modes

Preview only:

```env
AI_ENGINE_BATCH_PREVIEW_ONLY=true
AI_ENGINE_ASSEMBLED_REQUEST_PREVIEW_LIMIT=20
AI_ENGINE_PROCESS_LIMIT=5
```

Small live test:

```env
AI_ENGINE_BATCH_PREVIEW_ONLY=false
AI_ENGINE_PROCESS_LIMIT=10
```

Full run:

```env
AI_ENGINE_BATCH_PREVIEW_ONLY=false
AI_ENGINE_PROCESS_LIMIT=0
```

Strict quality mode:

```env
AI_ENGINE_MIN_CONFIDENCE=0.85
AI_ENGINE_FAIL_SCHEMA_VALIDATION=true
```

Cost-sensitive mode:

```env
AI_ENGINE_MIN_CONFIDENCE=0.75
AI_ENGINE_DIRECT_FLASH_IMAGE_THRESHOLD=3
AI_ENGINE_DIRECT_FLASH_COMPLEX_PROMPT_CHARS=4500
```
