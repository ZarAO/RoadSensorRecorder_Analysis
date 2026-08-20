// Regenerate src/design/tokens.css from tokens.json.
// Wraps the design-system skill's python generator, then renames the override
// selector: our default theme is DARK (:root), so the JSON's "dark" block holds
// the LIGHT overrides. A plain `sed` here broke under cmd.exe quoting once —
// hence this cross-platform script (see the inverted-theme bug, 2026-08-20).
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

const GENERATOR = 'C:/DEV/ai-agents/plugins/frontend-toolkit/skills/design-system/scripts/tokens_to_css.py';
const SRC = 'src/design/tokens.json';
const OUT = 'src/design/tokens.css';

const css = execFileSync('python', [GENERATOR, SRC], { encoding: 'utf8' });
const renamed = css.replace('[data-theme="dark"]', '[data-theme="light"]');
if (renamed === css) {
  throw new Error('override block not found — generator output changed?');
}
writeFileSync(OUT, renamed);
console.log(`${OUT} regenerated (dark = :root, light = [data-theme="light"])`);
