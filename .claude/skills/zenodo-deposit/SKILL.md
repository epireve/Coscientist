---
name: zenodo-deposit
description: Deposit a registered dataset to Zenodo and mint a DOI. Reads dataset_id from dataset-agent registry, packages files, calls Zenodo REST API with token from $ZENODO_TOKEN. Updates dataset state to `deposited` with DOI on success. Sandbox option for testing.
when_to_use: User says "deposit to Zenodo", "mint DOI", "publish dataset". Requires `ZENODO_TOKEN` env var (or `ZENODO_SANDBOX_TOKEN` with `--sandbox`).
---

# zenodo-deposit

Bridges `dataset-agent` to Zenodo. Real network calls — needs API token.

## Scripts

```
deposit.py prepare --dataset-id D — package metadata, dry-run only
deposit.py upload --dataset-id D [--sandbox] — real API call, mints DOI
deposit.py status --dataset-id D
```

## Prerequisites

- `ZENODO_TOKEN` env var with `deposit:write deposit:actions` scopes
- `ZENODO_SANDBOX_TOKEN` for `--sandbox` mode (testing against sandbox.zenodo.org)
- Dataset must already exist via `dataset-agent register` and have computed hashes

## What `prepare` does (dry-run)

1. Reads dataset record from `datasets/<id>/dataset.json`
2. Builds Zenodo metadata payload (title, description, creators, license, keywords)
3. Validates required fields (license is OSI/CC, paths exist, hashes computed)
4. Writes `datasets/<id>/zenodo_metadata.json` and prints what *would* upload
5. Does NOT call the API

## What `upload` does

1. Runs `prepare` first
2. Creates a deposit on Zenodo
3. Uploads each file in `paths`
4. Submits the deposit (mints DOI)
5. Updates `datasets/<id>/manifest.json` state → `deposited`, sets `doi`
6. Logs response to `datasets/<id>/zenodo_response.json`

## API endpoints used

- `POST /api/deposit/depositions`
- `POST /api/deposit/depositions/{id}/files`
- `POST /api/deposit/depositions/{id}/actions/publish`

## Safety

- Refuses to upload without a valid token
- Refuses if dataset record has no `paths` or hashes are stale
- `--sandbox` always uses sandbox.zenodo.org regardless of token type
- Real DOIs are permanent — `prepare` first, eyeball metadata, then `upload`
