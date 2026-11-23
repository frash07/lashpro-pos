# POS theme token contract

## Canonical ownership

`static/css/tokens.css` is the single source of truth for the POS design system:

- Premium brand: vivid pink `#E94F9B` with petal highlights, cool neutral light surfaces, and true obsidian dark surfaces (`#0B0B0F` canvas).
- Semantic roles for surfaces, borders, text, brand, success, warning, danger, and info.
- Light and dark theme values under `html[data-theme]`; the dark palette uses neutral obsidian/charcoal values and must not introduce brown, beige, taupe, or wine casts.
- UI/display fonts, radii, focus treatment, shadows, and reusable gradients.
- Compatibility aliases for older POS/admin component names. These are defined only in this file and should be retired as consumers are modernised.

Feature CSS files now consume variables for their colour values, radii, shadows, and font families. New styling should use semantic tokens such as `var(--brand)`, `var(--ui-surface)`, `var(--danger-soft)`, `var(--lp-radius-md)`, `var(--shadow-sm)`, and `var(--lp-font-ui)`. Do not add feature-level `:root` maps or hardcode theme values.

## Stylesheet loading

The shared base loads:

1. `tokens.css`
2. `legacy.css` (temporary selector-level compatibility rules only)
3. `components.css`
4. `legal.css`

Derived shells load their page/shell styles after this base stack. Standalone checkout does not extend `base.html`, so it explicitly loads the same token and component foundation before `checkout.css`, `admin-suite.css`, and `checkout-workspace.css`.

The legacy bridge is retained temporarily because older template selectors still use the compatibility class rules. It no longer defines its own token map. The Django admin integration file retains a `:root` block only to map Django's framework variables to the canonical tokens.

## Typography and theme modes

Inter is the only UI font; Playfair Display is the display font. Shared and page templates load the canonical font pair. Feature stylesheets consume `--lp-font-ui` and `--lp-font-display`. Auth, admin suite, checkout, and POS styles all consume the shared light/dark roles instead of defining parallel palettes.

## Legacy exceptions

`static/sales/reference-layout.css` is an unused dark POS mock-up with a large hard-coded dark palette. It has been explicitly quarantined and must not be included by templates. It should be deleted once maintainers confirm no external/legacy entry point depends on it.

`static/css/receipt.css` now consumes theme tokens for screen and print surfaces, status colours, radii, and shadows. The `--receipt-paper` token intentionally remains white so printed receipts retain paper fidelity.

## CI enforcement

`scripts/check_css_tokens.py` compares changed CSS with the branch base and fails if a feature stylesheet adds hard-coded colours, RGB/HSL functions, literal radii, literal shadows, or local font families. The receipt stylesheet is checked like other feature CSS. Only the quarantined reference mock-up and canonical token file are excluded.

The compatibility aliases can be removed in a later pass after their usages are converted to semantic names. Keep the guard enabled so the debt cannot grow again.
