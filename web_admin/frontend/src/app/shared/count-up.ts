import { Component, effect, input, signal } from '@angular/core';

const DURATION_MS = 700;

/** Animated numeric value for KPI cards; instant under reduced motion. */
@Component({
  selector: 'app-count-up',
  template: `<span class="num">{{ display() }}</span>`,
})
export class CountUp {
  readonly value = input.required<number>();
  readonly decimals = input(0);

  protected readonly display = signal('0');
  private raf = 0;

  constructor() {
    const reduced = typeof matchMedia !== 'undefined'
      && matchMedia('(prefers-reduced-motion: reduce)').matches;

    effect(() => {
      const target = this.value();
      cancelAnimationFrame(this.raf);
      if (reduced || !Number.isFinite(target)) {
        this.display.set(this.format(target));
        return;
      }
      const start = performance.now();
      const from = 0;
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / DURATION_MS);
        const eased = 1 - Math.pow(1 - t, 3);
        this.display.set(this.format(from + (target - from) * eased));
        if (t < 1) this.raf = requestAnimationFrame(tick);
      };
      this.raf = requestAnimationFrame(tick);
    });
  }

  private format(value: number): string {
    if (!Number.isFinite(value)) return '—';
    return value.toLocaleString('uk-UA', {
      minimumFractionDigits: this.decimals(),
      maximumFractionDigits: this.decimals(),
    });
  }
}
