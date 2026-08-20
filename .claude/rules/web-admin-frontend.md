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
