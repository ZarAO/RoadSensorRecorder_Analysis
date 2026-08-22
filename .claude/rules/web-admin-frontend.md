# Web admin frontend rules (path-scoped: web_admin/frontend/**)

- Angular 22 standalone: signal-based `input()`, `signal`/`computed` state,
  `inject()` over constructor params, built-in `@if`/`@for` control flow.
  OnPush is the v22 default — do not add zone-dependent patterns.
- DTOs in `src/app/api/dto.ts` mirror `web_admin/backend/src/api/schemas.py`
  verbatim; change them together.
- All HTTP goes through `ApiService`; components never call `HttpClient` directly.
  Dev server always runs with `--proxy-config proxy.conf.json` (backend on :8000).
- UI copy is Ukrainian; code and identifiers are English.
- Invariant from the analyzer: NEVER render a numeric `iri_multi` for a segment
  with `needs_class12_survey`/`low_speed_class` — show `—` plus the label, and
  keep the magenta `#FF00FF` marking with the legend
  «Потребує обстеження профілометром (клас 1/2)».
- Unit tests: colocated `.spec.ts`, run via `ng test --watch=false` (vitest builder);
  stub `ApiService` with plain objects + rxjs `of()`.
- Design tokens live in `src/design/tokens.json` (three layers, OKLCH, dark = default
  `:root`, light = `[data-theme="light"]`); regenerate `tokens.css` with `npm run tokens`.
  Components read ONLY `var(--...)` — no raw hex/px outside the primitive layer.
  Exception: the IRI severity scale + #FF00FF magenta on maps is a data contract, not UI theme.
- Style: control-room dark, Restrained color commitment (single sky accent <=10%);
  no glow shadows, no glassmorphism panels, no side-stripe accents (ai-slop catalog).
- Theme switch: ThemeService toggles `data-theme` on <html>, persisted in localStorage;
  index.html applies it pre-paint. Map tiles follow the theme (CARTO dark/light).
- All contrast pairs verified AA with the ui-quality-gates contrast.py — re-run it
  after any token color change.
- All maps render through the shared `shared/segment-map.ts` component — the
  IRI severity palette and the `#FF00FF` class-1/2 magenta live there as a
  data contract, not duplicated per page.
- Comparison/calibration charts are hand-rolled SVG only — no chart libraries,
  no KaTeX; match the existing scatter/profile/Bland–Altman implementations.
  `shared/charts/multi-line-chart.ts` (`MultiLineChart`) is the shared N-series
  +band line chart (reference profile, aggregate profile) — reuse it instead
  of hand-rolling another line chart.
- `calibration/create-set-dialog.ts` (`CreateSetDialog`) is the single
  "Створити набір коефіцієнтів" dialog, shared by the comparison and the
  aggregate detail pages (provenance `{kind: 'comparison'|'aggregate', id}`) —
  do not add a second set-creation dialog.
