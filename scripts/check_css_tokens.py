#!/usr/bin/env python3
"""Prevent changed POS stylesheets from adding raw theme values.

Canonical values live in static/css/tokens.css. Existing, untouched migration
debt is tolerated; any increase in raw colours, radii, shadows, or font-family
declarations in changed feature CSS fails CI.
"""
from __future__ import annotations

import collections
import os
import re
import subprocess
import sys

EXEMPT_ENTIRE_PATHS = {
    "static/css/tokens.css",
    "static/sales/reference-layout.css",
}
HEX_COLOUR = re.compile(
    r"(?<![\w-])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|"
    r"[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])"
)
RAW_COLOUR_FUNCTION = re.compile(
    r"\b(?:rgb|rgba|hsl|hsla)\s*\(([^()]*)\)", re.IGNORECASE
)
DECLARATION = {
    "border-radius": re.compile(r"border-radius\s*:\s*([^;}]+)", re.IGNORECASE),
    "box-shadow": re.compile(r"box-shadow\s*:\s*([^;}]+)", re.IGNORECASE),
    "font-family": re.compile(r"font-family\s*:\s*([^;}]+)", re.IGNORECASE),
    "font": re.compile(r"\bfont\s*:\s*([^;}]+)", re.IGNORECASE),
}


def git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_css_files(base_ref: str) -> list[str]:
    names = git_text(
        "diff", "--name-only", "--diff-filter=ACMRT", f"{base_ref}...HEAD", "--", "*.css"
    )
    return [name for name in names.splitlines() if name.endswith(".css")]


def source_at(ref: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def declaration_values(source: str, pattern: re.Pattern[str]) -> list[str]:
    return [match.group(1).strip() for match in pattern.finditer(source)]


def is_literal_radius(value: str) -> bool:
    return "var(" not in value and value.lower() not in {
        "0", "0px", "none", "inherit", "initial", "unset", "revert"
    }


def is_literal_shadow(value: str) -> bool:
    return "var(" not in value and value.lower() not in {
        "none", "inherit", "initial", "unset", "revert"
    }


def is_literal_font(value: str) -> bool:
    return "var(" not in value and not re.search(
        r"\b(?:inherit|initial|unset|revert|monospace)\b",
        value,
        re.IGNORECASE,
    )


def theme_value_counts(source: str) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)

    # Count hex values only within declaration blocks, not selectors like #content.
    depth = 0
    for line in source.splitlines():
        depth_before_char = depth
        for match in HEX_COLOUR.finditer(line):
            before = line[:match.start()]
            local_depth = depth_before_char + before.count("{") - before.count("}")
            if local_depth > 0:
                counts[f"colour {match.group(0).lower()}"] += 1
        depth += line.count("{") - line.count("}")

    for match in RAW_COLOUR_FUNCTION.finditer(source):
        counts[f"colour function {match.group(0).lower()}"] += 1

    for value in declaration_values(source, DECLARATION["border-radius"]):
        if is_literal_radius(value):
            counts[f"border-radius: {value}"] += 1

    for value in declaration_values(source, DECLARATION["box-shadow"]):
        if is_literal_shadow(value):
            counts[f"box-shadow: {value}"] += 1

    for property_name in ("font-family", "font"):
        for value in declaration_values(source, DECLARATION[property_name]):
            if is_literal_font(value):
                counts[f"{property_name}: {value}"] += 1

    return counts


def main() -> int:
    base_ref = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("GITHUB_BASE_REF") and f"origin/{os.environ['GITHUB_BASE_REF']}"
        or os.environ.get("GITHUB_EVENT_BEFORE")
        or "HEAD^"
    )
    if base_ref == "0000000000000000000000000000000000000000":
        base_ref = "HEAD^"

    try:
        paths = changed_css_files(base_ref)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or f"Unable to compare stylesheets against {base_ref}.", file=sys.stderr)
        return 2

    violations: list[str] = []
    for path in paths:
        if path in EXEMPT_ENTIRE_PATHS:
            continue
        baseline = theme_value_counts(source_at(base_ref, path))
        current = theme_value_counts(source_at("HEAD", path))
        for value, count in (current - baseline).items():
            violations.append(f"{path}: introduced {count} raw {value} value(s)")

    if violations:
        print("POS theme-token policy failed. Consume variables from static/css/tokens.css:")
        print("\n".join(f"  - {item}" for item in violations))
        return 1

    print("POS theme-token policy passed: changed stylesheets add no raw theme values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
