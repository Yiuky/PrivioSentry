# PRIVIO SENTRY — UX Specification v0.2

## Primary workflow

### 01 — Import

**Title**
Protect a document

**Subtitle**
Detect sensitive information locally and review it before applying protection.

**State**
`LOCAL PROCESSING`

Actions:
- Browse files
- Drop file

Supported initial formats:
- PDF
- PNG
- JPG/JPEG
- TIFF

---

### 02 — Analyze

**Title**
Analyzing document

Pipeline:
`OCR → Detection → Classification → Policy check`

Text:
`Processing locally`

Do not expose raw sensitive values in progress logs.

---

### 03 — Review

**Title**
Review detections

Summary:
`18 potential sensitive elements detected`

Filters:
- All
- Personal Data
- Sensitive Personal Data
- Secrets
- Financial
- Custom

Each item:
`Category · confidence · page · region`

Actions:
- Accept
- Reject
- Edit region
- Change category

---

### 04 — Detection detail

Example:

`CPF`

`Confidence 98%`

`Page 3 · Region 12`

Suggested action:
`Redact permanently`

Warning:
`AI detection is probabilistic. Verify the selection before export.`

---

### 05 — Protection

**Title**
Apply protection

Summary:
`16 accepted`
`2 rejected`
`1 manually edited`

Mode:
- Permanent redaction
- Mask
- Pseudonymize

Primary:
`Apply protection`

---

### 06 — Completion

**Title**
Protection complete

Summary:
`18 elements processed`

Status:
`Processed locally`

Actions:
`Export protected document`
`View audit`

---

## Information architecture

### Dashboard
- New protection job
- Recent jobs
- Review queue
- Local status

### Documents
- In progress
- Completed
- Failed
- Deleted

### Policies
- Built-in
- Custom
- Version history

### Models
- Installed
- Active
- Version
- Hardware utilization

### Audit
- Jobs
- Evidence
- Export

### Settings
- Privacy
- Storage
- Network
- Models
- Localization

---

## Copy rules

Prefer:
- `potential`
- `detected`
- `suggested`
- `review`
- `policy`
- `protected`

Avoid:
- `guaranteed`
- `100% secure`
- `AI knows`
- `fully compliant`

---

## Localization keys

Use keys, not Portuguese or English literals in code.

```text
dashboard.protect.title
dashboard.local.badge
detection.review.title
detection.confidence.label
policy.lgpd.title
policy.apply.action
protection.complete.title
audit.view.action
settings.privacy.title
```

Initial locales:
- pt-BR
- en-US
- es
- fr
- de
