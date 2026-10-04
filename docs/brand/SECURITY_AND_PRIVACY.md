# PRIVIO SENTRY — Security & Privacy Model v0.2

## Objective

Minimize data exposure while keeping the processing pipeline inspectable.

## Threat model

Consider at least:
- unauthorized access to original files;
- temporary file leakage;
- OCR artifact leakage;
- logs containing raw PII;
- model prompts containing source text;
- embeddings persisting sensitive information;
- output files retaining hidden text;
- metadata leakage;
- network egress;
- insecure plugins/extensions;
- compromised local process.

## Default principles

### 1. No raw PII in logs
Detection logs should record category and region, not the raw value.

### 2. Hash inputs/outputs for evidence
Use cryptographic hashes to identify artifacts without copying their contents into the audit record.

### 3. Temporary-file lifecycle
Document exactly when originals and intermediate artifacts are created, used and deleted.

### 4. Network policy
Provide an explicit network state:
`LOCAL / OFFLINE / CONTROLLED NETWORK`

### 5. Model provenance
Audit records should include:
- model name;
- version;
- runtime;
- policy version.

### 6. Output verification
For PDF redaction, verify that hidden text/content is not recoverable through common extraction methods where the selected protection mode claims irreversible redaction.

## Local processing indicator

The UI can say:

`LOCAL PROCESSING`

Only say:

`NO NETWORK ACCESS`

when the application can technically enforce that state.

## Audit example

```json
{
  "job_id": "job_01",
  "processing_mode": "local",
  "network_mode": "disabled",
  "model": "local-model",
  "model_version": "x.y.z",
  "policy": "lgpd-personal-data-v1",
  "input_sha256": "...",
  "output_sha256": "...",
  "detections": 18,
  "accepted": 16,
  "rejected": 2,
  "overridden": 1,
  "started_at": "...",
  "completed_at": "..."
}
```

## Sensitive-value handling

Do not put:
- CPF;
- full names;
- addresses;
- tokens;
- API keys;
- signatures;
- extracted health information

into standard application logs.

If debugging requires samples, use synthetic or explicitly approved redacted fixtures.

## LGPD relation

The security architecture supports, among other objectives, confidentiality, integrity, prevention and accountability. It does not by itself establish legal compliance.
