# POS theme token contract

## Canonical ownership

`static/css/tokens.css` is the single source of truth for POS CSS custom properties. It owns:

- Brand and semantic colour roles (`--brand`, `--ui-canvas`, `--ui-surface`, `--ui-text`, `--success`, `--warning`, `--danger`, and `--info`).
- Light and dark theme values under `html[data-theme]`.
- Font-family tokens, radii, focus treatment, elevations, gradients, receipt surfaces and framework adapters.
- Temporary compatibility aliases for older templates and integrations.

No other POS stylesheet may declare custom properties. Feature stylesheets and component stylesheets consume tokens; they do not define a local `:root`, theme map, or fallback palette. Django Admin's `--primary`, `--body-bg`, breadcrumb and related framework variables are adapters declared centrally in `tokens.css`; `static/admin/css/lashpro-admin.css` contains selectors only.

**This pass is structural.** It does not change the active palette, font families, font sizes, or page layout dimensions. Palette refinement is a separate future task.

## Semantic token usage

Use semantic roles rather than palette scale names. Examples:

| Purpose | Canonical token |
|---|---|
| Main page background | `var(--ui-canvas)` |
| Card / panel surface | `var(--ui-surface)` |
| Muted / nested surface | `var(--ui-surface-muted)` |
| Raised surface | `var(--ui-surface-raised)` |
| Main text | `var(--ui-text)` |
| Secondary text | `var(--ui-muted)` |
| Subtle / disabled text | `var(--ui-subtle)` |
| Primary accent | `var(--brand)` |
| Accent hover | `var(--brand-hover)` |
| Soft accent fill | `var(--brand-soft)` |
| Borders | `var(--ui-border)`, `var(--ui-border-strong)` |
| Status colours | `var(--success)`, `var(--warning)`, `var(--danger)`, `var(--info)` |
| UI / display / monospace font | `var(--lp-font-ui)`, `var(--lp-font-display)`, `var(--lp-font-mono)` |
| Radius / elevation / focus | `var(--lp-radius-md)`, `var(--shadow-sm)`, `var(--lp-focus)` |

## Deprecated names and replacements

The old names remain defined in `tokens.css` as a transition bridge for legacy template markup and external integrations. Do not use them in new or migrated feature CSS.

| Deprecated name(s) | Use instead |
|---|---|
| `--bg`, `--canvas` | `--ui-canvas` |
| `--bg-2`, `--surface-2`, `--rose-50` | `--ui-surface-muted` |
| `--surface`, `--surface-1`, `--paper`, `--rose-25` | `--ui-surface` |
| `--surface-3`, `--surface-raised` | `--ui-surface-raised` |
| `--text`, `--ink`, `--ink-700`, `--ink-900` | `--ui-text` |
| `--muted`, `--muted-bright`, `--ink-500` | `--ui-muted` |
| `--subtle`, `--muted2` | `--ui-subtle` |
| `--line`, `--border`, `--rose-150` | `--ui-border` |
| `--line-strong`, `--line2`, `--border-strong`, `--rose-200` | `--ui-border-strong` |
| `--pink*`, `--rose*`, `--lp-pink-*` | `--brand`, `--brand-hover`, `--brand-soft`, `--premium-petal`, or `--premium-petal-soft` according to role |
| `--green*`, `--red*`, `--amber*`, `--gold*`, `--blue` | `--success*`, `--danger*`, `--warning*`, `--info*` |
| `--font-ui`, `--font-display` | `--lp-font-ui`, `--lp-font-display` |
| `--focus-ring`, `--shadow`, `--radius*`, `--r` | `--lp-focus`, `--shadow-*`, `--lp-radius-*` |
| `--field-bg`, `--field-border` | `--ui-surface`, `--ui-border-strong` |
| `--hero-start`, `--hero-mid`, `--hero-end`, `--bg-gradient` | `--hero-gradient`, `--ui-surface-gradient`, or `--ui-canvas-gradient` as appropriate |
| `--lp-neutral-*`, `--lp-surface*`, `--lp-text*`, `--lp-border*`, `--lp-btn-*`, `--lp-success*`, `--lp-shadow-*` | Corresponding semantic `--ui-*`, `--brand*`, status, shadow or radius tokens |

The `--lp-compat-*` names are one-off migration adapters for legacy literal radii, shadows and colours. They are centralized in `tokens.css`; do not add new compatibility hashes. Replace them with a named semantic token when a component is next modernized.

## Stylesheet loading and ownership

- Shared staff POS pages extending `base.html` load `tokens.css`, then `components.css`, then common `legal.css`. Shell and page stylesheets load afterwards through `head_extra`.
- Standalone POS entry points must load `tokens.css` first, `components.css` second when they use shared primitives, and then their page stylesheets. Checkout, Admin Suite and Cash Session follow this order.
- Django Admin loads its framework stylesheet, then the POS `tokens.css` adapter layer, then `lashpro-admin.css`, then the relevant page-specific stylesheet. `components.css` is included only on custom admin pages that use its POS primitives; it is intentionally not injected into every Django Admin screen because it contains broad legacy selectors.
- Page-specific styles belong in their page stylesheet, not in template `<style>` blocks or `style=` attributes. Add a class and keep the rule token-based.

## Legacy selector retirement

The separate `static/css/legacy.css` file has been retired. Its still-needed selector rules are retained at the top of `components.css`, before current component rules, to preserve the former cascade order. This includes legacy template buttons, status classes, table wrappers and the minimal print body rule. Those selectors can be removed when the remaining legacy markup is migrated.

`static/sales/reference-layout.css` remains quarantined and must not be included by a POS template. It is an unused reference mock-up, not part of the runtime design system.

## Typography and receipts

This harmonization does not change font families or sizes. Shared UI and display styles consume `--lp-font-ui` and `--lp-font-display`; the monospace token preserves the existing code-like checkout treatment. Receipt print stock remains white through `--receipt-paper`.

## CI enforcement

- `scripts/check_css_tokens.py` prevents changed stylesheets from introducing additional literal colours, radii, shadows or font declarations.
- `scripts/check_pos_css_contract.py` checks that no runtime POS stylesheet declares custom properties outside `tokens.css` and that feature CSS does not consume deprecated aliases.
- Keep both checks enabled. Compatibility declarations may remain in `tokens.css` temporarily, but feature CSS should continue moving to semantic names.


## Audited template and stylesheet inventory

The harmonization audit covered **71 non-storefront HTML templates** and **45 POS CSS assets**. Every template under `templates/` outside `templates/storefront/` was checked for inline `style=` attributes and embedded `<style>` blocks; none remain. Page-specific rules formerly embedded in checkout, inventory import, supplier receipt and Catalog/Commissions hub templates now live in external stylesheets.

The principal loading groups are:

| Screen / template group | Shared foundation | Page-specific layer |
|---|---|---|
| General staff pages extending `base.html` | `tokens.css` → `components.css` → `legal.css` | Loaded through each page's `head_extra` |
| Authentication shell | Shared base foundation | `auth.css` |
| Admin shell | Shared base foundation | `admin-shell.css`, then page-specific CSS |
| POS shell | Shared base foundation | `pos.css` |
| Standalone Checkout | `tokens.css` → `components.css` | `checkout.css` → `admin-suite.css` → `checkout-workspace.css` → `legal.css` |
| Standalone Admin Suite | `tokens.css` → `components.css` | `admin-suite.css` |
| Standalone Cash Session | `tokens.css` → `components.css` | `checkout.css` → `cash-session.css` |
| Django Admin | Django admin framework → `tokens.css` → `lashpro-admin.css` | App/model stylesheet after the framework adapter |
| Inventory Receive | Shared base foundation | `checkout.css` → `receive.css` |
| Product Import | Shared base foundation | `product-import.css` |
| Supplier receipt history and detail | Shared base foundation | `receipts.css` |
| Reporting dashboard | Shared base foundation | `reporting/dashboard.css` |
| Receipt | Shared base foundation | `receipt.css` |
| Training pages | Shared base foundation | `training.css` |

Django Admin's custom app-index pages load their own page styles after the framework adapter. The custom Sale register explicitly loads `components.css` because it uses the shared legacy button/status/table primitives; those broad selectors are not injected into every Django Admin model screen.

## Inline-style and hard-coded-value audit

- No inline style attributes or embedded style blocks remain in the 71 audited POS templates.
- The generated Catalog admin thumbnail now uses a class and the canonical radius token rather than inline width, height, object-fit and radius declarations.
- Runtime POS CSS was checked for literal hex colours, literal RGB/HSL functions, un-tokenized radii and un-tokenized shadows. No such values remain in the runtime feature stylesheets.
- Feature CSS font-family declarations and font shorthand now resolve through the UI, display or monospace font tokens. The separate reference mock-up is excluded.

Two deliberately self-contained network-failure responses are exceptions to the template stylesheet contract: `static/pwa/offline.html` and the transient HTML response generated in `core/views.py` when a POST request loses connectivity. They remain standalone so the offline and unknown-request states do not depend on a stylesheet being available at the moment of failure. These are not regular POS screens or page templates. The PWA fallback and reference mock-up are separately isolated from the runtime token contract.
