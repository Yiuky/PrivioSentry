# PRIVIO SENTRY — Product Design Guidelines v0.2

## 1. Experience goal

The interface must make the user feel:

> “I know what the AI saw, I know what the system will do, and I remain in control.”

The visual system must emphasize controlled review instead of one-click automation.

---

## 2. Design principles

### Local by default
Show processing location prominently.

### Explainable detection
Every detection should expose category and confidence.

### Human confirmation
Irreversible operations require review.

### Policy driven
The model detects; a policy determines the desired treatment.

### Minimal retention
Originals and intermediate artifacts should not be stored longer than necessary.

### Evidence
Completed jobs should be auditable.

---

## 3. Main application structure

```text
Dashboard
Documents
Policies
Models
Audit
Settings
```

### Dashboard hierarchy

1. `Protect a document`
2. `LOCAL PROCESSING`
3. Current policy
4. Recent jobs
5. Items requiring review

---

## 4. Visual grammar

### Surfaces
White cards on a very light neutral background.

### Controls
8 px radius, 1 px borders.

### Major panels
12–16 px radius.

### Shadows
Subtle only. Avoid “floating UI everywhere”.

### Icons
Simple outline/solid hybrid. No novelty icons.

---

## 5. Document viewer

The review screen is the product’s most important surface.

Recommended arrangement:

```text
┌──────────────────────────────┬─────────────────────────┐
│                              │ REVIEW                  │
│       DOCUMENT VIEWER        │                         │
│                              │ 18 detections           │
│        [content]             │                         │
│  [██████]        [████]      │ CPF             98%    │
│                              │ Email           93%    │
│        [████████]             │ Address         88%    │
│                              │ Signature       62%    │
└──────────────────────────────┴─────────────────────────┘
```

---

## 6. Detection visualization

Each detection has:
- bounding region;
- category;
- confidence;
- state.

States:

`Detected`
`Selected`
`Reviewed`
`Protected`
`Rejected`
`Edited`

Never communicate confidence with color alone.

---

## 7. Protection policy

Policies should be first-class objects.

Example:

```yaml
name: LGPD Personal Data Review
scope:
  - PERSONAL_DATA
actions:
  CPF: redact
  EMAIL: mask
  PHONE: mask
  NAME: review
```

The exact policy language should be configurable to each organization.

---

## 8. “LGPD mode”

Preferred UI label:

**LGPD-aligned protection policy**

Do not use:

**LGPD Compliant**

Supporting text:

> Applies configurable protection rules to categories relevant to personal-data handling under the LGPD. Review detections before export.

---

## 9. Completion

Use:

> **Protection complete**

Then:

`18 elements processed`

`Processed locally`

Actions:
- `Export protected document`
- `View audit`

Avoid:

> “Your document is now LGPD compliant.”

---

## 10. Empty states

### No document
`No documents yet`
`Add a PDF or image to begin detection.`

### No detection
`No sensitive content detected`
`Detection is probabilistic and does not guarantee that the document contains no personal or confidential information.`

### Review queue empty
`Nothing needs review`
`All current detections have been resolved.`

---

## 11. Accessibility

Target WCAG-oriented practices:
- keyboard navigation;
- visible focus state;
- adequate contrast;
- labels for icons;
- no color-only state encoding;
- zoomable document viewer;
- readable text at 200% zoom.

Keyboard shortcuts:

`A` Accept
`R` Redact selected
`X` Reject
`N` Next
`P` Previous
`Ctrl/Cmd+Z` Undo

---

## 12. Responsive behavior

Desktop-first.

At widths below 900 px:
- collapse navigation;
- stack document and review panels;
- keep review actions sticky.

---

## 13. Motion

Motion should explain state changes.

Example:

`Detecting → reviewing → protected`

Avoid decorative animation unrelated to user action.
