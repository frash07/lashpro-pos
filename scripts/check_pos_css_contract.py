#!/usr/bin/env python3
"""Enforce one POS token source and prevent new deprecated-token consumers."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = "static/css/tokens.css"
QUARANTINED = {"static/sales/reference-layout.css"}
POS_CSS_ROOTS = (
    "static/accounts",
    "static/admin/css",
    "static/catalog",
    "static/core",
    "static/css",
    "static/inventory",
    "static/reporting",
    "static/sales",
    "static/training",
)

CUSTOM_PROPERTY = re.compile(r"(?m)^\s*(--[a-zA-Z0-9_-]+)\s*:")
VAR_REFERENCE = re.compile(r"var\(\s*(--[a-zA-Z0-9_-]+)")
CSS_COMMENT = re.compile(r"/\*[\s\S]*?\*/")

DEPRECATED_EXACT = {
    "--bg", "--bg-2", "--bg-gradient", "--canvas", "--paper",
    "--surface", "--surface-1", "--surface-2", "--surface-3", "--surface-raised", "--surface-soft",
    "--text", "--ink", "--ink-500", "--ink-700", "--ink-900",
    "--muted", "--muted-bright", "--muted2", "--subtle",
    "--line", "--line2", "--line-strong", "--border", "--border-strong",
    "--pink", "--pink-50", "--pink-100", "--pink-200", "--pink-600", "--pink-700",
    "--pink-strong", "--pink-deep", "--pink-soft", "--pink-wash",
    "--rose", "--rose-light", "--rose-deep", "--rose-wash", "--rose-rgb",
    "--rose-25", "--rose-50", "--rose-100", "--rose-150", "--rose-200",
    "--rose-300", "--rose-400", "--rose-500", "--rose-600", "--rose-700", "--rose-800",
    "--gold", "--gold-bg", "--success-bg", "--danger-bg", "--warning-bg",
    "--green", "--green-bg", "--green-100", "--green-600",
    "--amber", "--amber-100", "--amber-600",
    "--red", "--red-100", "--red-600", "--blue",
    "--font-ui", "--font-display", "--focus-ring", "--shadow", "--radius",
    "--radius-sm", "--r", "--field-bg", "--field-border",
    "--hero-start", "--hero-mid", "--hero-end",
    "--lp-text", "--lp-text-muted", "--lp-surface", "--lp-surface-alt",
    "--lp-surface-strong", "--lp-surface-ink", "--lp-border", "--lp-border-strong",
    "--lp-btn-primary-bg", "--lp-btn-primary-text", "--lp-btn-primary-hover",
    "--lp-success", "--lp-success-soft", "--lp-warning", "--lp-warning-soft",
    "--lp-danger", "--lp-danger-soft", "--lp-info",
    "--lp-shadow-sm", "--lp-shadow-md", "--lp-shadow-lg",
}
DEPRECATED_PREFIXES = (
    "--lp-neutral-",
    "--lp-pink-",
)

def pos_css_files() -> list[Path]:
    files: list[Path] = []
    for root in POS_CSS_ROOTS:
        folder = ROOT / root
        if folder.exists():
            files.extend(folder.rglob("*.css"))
    return sorted(
        path for path in set(files)
        if path.relative_to(ROOT).as_posix() != TOKEN_FILE
        and path.relative_to(ROOT).as_posix() not in QUARANTINED
    )

def main() -> int:
    errors: list[str] = []
    for path in pos_css_files():
        relative = path.relative_to(ROOT).as_posix()
        source = CSS_COMMENT.sub("", path.read_text(encoding="utf-8"))
        declarations = CUSTOM_PROPERTY.findall(source)
        for name in declarations:
            errors.append(f"{relative}: custom property {name} must be declared in {TOKEN_FILE}")
        for name in set(VAR_REFERENCE.findall(source)):
            deprecated = name in DEPRECATED_EXACT or any(name.startswith(prefix) for prefix in DEPRECATED_PREFIXES)
            if deprecated:
                errors.append(f"{relative}: deprecated token {name}; use its semantic replacement from {TOKEN_FILE}")

    if errors:
        print("POS CSS contract failed:")
        print("\n".join(f"  - {error}" for error in errors))
        return 1

    print("POS CSS contract passed: tokens.css owns custom properties and feature CSS uses semantic tokens.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
