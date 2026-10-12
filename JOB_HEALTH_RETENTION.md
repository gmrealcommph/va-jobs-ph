# Retain job records for Job Health

Job reclassification currently hard-deletes published jobs. This companion change retains those records as inactive instead, preserving their IDs and the existing classification/visibility outcome. Source-missing reconciliation already uses inactive status and is unchanged. Publishing again reuses the same unique source/ID record. Stale job_reviews classifications can still be removed when publishing.

Two offline persistence tests exercise legacy and batched retirement, cross-source ID isolation, review cleanup and reopening without replacing the job record. The tests load only the persistence functions from the AST, avoiding collectors, credentials and network access. No live importer command was run.

This is a dependency for the web Job Health migration, whose reports/evidence retain foreign-key references to jobs. **Do not merge until rollout is approved:** the default branch runs against production every six hours. No schedule or deployment configuration was changed, and no branch workflow was dispatched.
