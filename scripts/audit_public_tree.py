#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-publication audit: look for PII, secrets and local paths in the publishable tree.

The "publishable tree" is what git would publish from the working directory:
tracked + untracked-but-not-ignored files (`git ls-files -co --exclude-standard`).
Files that are tracked but match .gitignore are reported separately (they would still
be published by a plain `git push`; remove them from the index with `git rm --cached`).

Checks
  * CPFs (formatted or 11 digits) with valid check digits that are NOT in the allowlist
  * e-mail addresses (except allowlisted placeholder domains)
  * org / user identifiers (configurable: AUDIT_TERMS below)
  * Windows absolute paths such as C:\\Users\\... or C:\\<project>
  * token / key shaped strings (API keys, private key headers, bearer tokens)
  * PDFs: extracted text is scanned too; other binary files are skipped

Usage:  python scripts/audit_public_tree.py [--root PATH] [--strict]
Exit code 1 if any finding (or, with --strict, any warning) is reported.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# CPFs that are fictional/public test numbers used in tests, docs and examples.
ALLOWED_CPFS = {
    "52998224725",  # 529.982.247-25  (classic valid test CPF)
    "11144477735",  # 111.444.777-35
    "39053344705",  # 390.533.447-05
    "12345678909",  # 123.456.789-09
    "00000000604",  # synthetic mod-11 edge case (unit test)
    "00000000191",  # synthetic mod-11 edge case (unit test)
}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "users.noreply.github.com"}
ALLOWED_EMAILS = {"noreply@anthropic.com"}
# Case-insensitive substrings that must never appear in the public tree. Extend as needed.
# The author's public identity (name, @Yiuky, GitHub noreply e-mail, Pix for donations) is allowed, as in
# ArcMagery; what stays blocked is the local Windows user name (it shows up in leaked paths), the
# employer's domain/acronym (personal project: it does not speak for any institution) and old folder names.
AUDIT_TERMS = ["joberthgambati", "sema.mt", "TARJADOR_2"]
# Word-bounded, case-sensitive terms (avoid matching inside normal words)
AUDIT_WORDS = ["SEMA"]
# Files that legitimately list the terms above (this script itself).
SELF_EXEMPT = {"scripts/audit_public_tree.py"}

CPF_RE = re.compile(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WINPATH_RE = re.compile(r"[A-Za-z]:\\+(?:Users|TARJADOR|Documents and Settings)[^\s\"'<>|]*", re.I)
# Real process/case identifiers seen in the original working directory (e.g. 7000843_2024_CAR MT220158_2022_ART)
PROCESS_ID_RE = re.compile(r"\b\d{7}_\d{4}_CAR\b|\bCAR MT\d+|\bMT\d{5,}_\d{4}_ART\b", re.I)
SECRET_RES = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai/anthropic-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "generic secret assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*['\"]?([A-Za-z0-9_\-/+=]{16,})['\"]?"),
    ),
]
TEXT_EXT_SKIP = {".pt", ".traineddata", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".woff", ".woff2", ".pyc"}


def cpf_valid(d: str) -> bool:
    nums = [int(c) for c in d]
    if len(set(nums)) == 1:
        return False
    for n in (9, 10):
        s = sum(nums[i] * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != nums[n]:
            return False
    return True


def git(root, *args):
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out.stdout.splitlines()


def read_text(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT_SKIP:
        return None
    if ext == ".pdf":
        try:
            import fitz  # type: ignore

            with fitz.open(path) as doc:
                return "\n".join(p.get_text() for p in doc) + "\n" + str(doc.metadata)
        except Exception:
            return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def scan(rel: str, text: str, findings: list):
    def line_of(pos):
        return text.count("\n", 0, pos) + 1

    for m in CPF_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if cpf_valid(digits) and digits not in ALLOWED_CPFS:
            masked = digits[:3] + ".***.***-" + digits[-2:]
            findings.append((rel, line_of(m.start()), "CPF (valid, not allowlisted)", masked))
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0)
        if addr.lower() in ALLOWED_EMAILS or addr.split("@")[1].lower() in ALLOWED_EMAIL_DOMAINS:
            continue
        findings.append((rel, line_of(m.start()), "e-mail", addr))
    low = text.lower()
    for term in AUDIT_TERMS:
        for m in re.finditer(re.escape(term.lower()), low):
            findings.append((rel, line_of(m.start()), "forbidden term", term))
    for term in AUDIT_WORDS:
        for m in re.finditer(r"\b" + re.escape(term) + r"\b", text):
            findings.append((rel, line_of(m.start()), "forbidden term", term))
    for m in PROCESS_ID_RE.finditer(text):
        findings.append((rel, line_of(m.start()), "real process/case identifier", m.group(0)))
    for m in WINPATH_RE.finditer(text):
        findings.append((rel, line_of(m.start()), "absolute Windows path", m.group(0)[:80]))
    for label, rx in SECRET_RES:
        for m in rx.finditer(text):
            val = m.group(0)
            if label == "generic secret assignment" and re.search(r"(?i)(example|your|changeme|placeholder|xxxx|\$\{|<)", val):
                continue
            findings.append((rel, line_of(m.start()), f"possible secret ({label})", val[:6] + "..."))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--strict", action="store_true", help="treat warnings (tracked-but-ignored files) as failures")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    files = sorted(set(git(root, "ls-files", "-co", "--exclude-standard")))
    ignored_tracked = sorted(set(git(root, "ls-files", "-ci", "--exclude-standard")))
    ignored_set = set(ignored_tracked)
    publishable = [f for f in files if f not in ignored_set]

    findings: list = []
    warnings: list = []
    total = 0
    for rel in publishable:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        total += 1
        size = os.path.getsize(path)
        if size > 5 * 1024 * 1024:
            warnings.append(f"large file ({size / 1e6:.1f} MB): {rel}")
        # file names themselves can leak process numbers / names
        for term in AUDIT_TERMS:
            if term.lower() in rel.lower():
                findings.append((rel, 0, "forbidden term in file name", term))
        if rel.replace("\\", "/") in SELF_EXEMPT:
            continue
        text = read_text(path)
        if text is not None:
            scan(rel, text, findings)
        elif rel.lower().endswith(".pdf"):
            warnings.append(f"PDF could not be text-scanned (install PyMuPDF): {rel}")
    for rel in ignored_tracked:
        warnings.append(f"tracked in git but ignored by .gitignore (remove from index / do not copy): {rel}")

    print(f"Audited {total} publishable files under {root}")
    if findings:
        print(f"\n{len(findings)} FINDING(S):")
        for rel, ln, kind, val in findings:
            print(f"  {rel}:{ln}: {kind}: {val}")
    else:
        print("No PII/secret findings.")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print("  " + w)
    return 1 if findings or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
