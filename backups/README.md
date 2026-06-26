# Batch-classification baseline

`pre_batch_baseline_20260622.zip` is the exact implementation immediately before multi-question batching was introduced. It includes the subject-specific DOK fixes.

- SHA-256: `F1E86D124FA052E15989A1355B651028B0EB040A5952C18C575565C4576F5E19`
- Created: 2026-06-22 11:52:45 Asia/Calcutta

When the user requests **revert to base**, restore the files from this archive into the project root and remove batch-only files introduced after the snapshot.

Batching can be disabled without restoring files by setting:

```text
AI_ENGINE_BATCH_ENABLED=false
```
