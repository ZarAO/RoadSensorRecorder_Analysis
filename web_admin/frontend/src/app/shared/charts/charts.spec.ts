import { TestBed } from '@angular/core/testing';

import { ChartBAPoint, ChartProfilePoint, ChartScatterPoint } from '../../api/dto';
import { BaChart } from './ba-chart';
import { extent, invertScale, linearScale, niceTicks, tickLabel } from './chart-scale';
import { ProfileChart } from './profile-chart';
import { ScatterChart } from './scatter-chart';

const SCATTER: ChartScatterPoint[] = [
  { seg_id: 1, psd_sqrt_scalar: 0.010, iri_ref: 2.0, iri_multi: 3.4, chainage_m: 0 },
  { seg_id: 2, psd_sqrt_scalar: 0.020, iri_ref: 3.5, iri_multi: 5.1, chainage_m: 100 },
  { seg_id: 3, psd_sqrt_scalar: 0.030, iri_ref: 5.0, iri_multi: 6.8, chainage_m: 200 },
];

const PROFILE: ChartProfilePoint[] = [
  { chainage_m: 0, iri_ref: 2.0, iri_multi: 3.4, iri_multi_bias_corrected: 1.9, seg_id: 1 },
  { chainage_m: 100, iri_ref: 3.5, iri_multi: 5.1, iri_multi_bias_corrected: 3.6, seg_id: 2 },
  { chainage_m: 200, iri_ref: 5.0, iri_multi: 6.8, iri_multi_bias_corrected: 5.3, seg_id: 3 },
];

const BA: ChartBAPoint[] = [
  { seg_id: 1, mean: 2.7, diff: 1.4 },
  { seg_id: 2, mean: 4.3, diff: 1.6 },
  { seg_id: 3, mean: 5.9, diff: 1.8 },
];

describe('chart-scale', () => {
  it('maps the domain onto the range linearly', () => {
    const scale = linearScale([0, 10], [0, 100]);
    expect(scale(0)).toBe(0);
    expect(scale(5)).toBe(50);
    expect(scale(10)).toBe(100);
  });

  it('supports an inverted range (SVG y axis grows downwards)', () => {
    const scale = linearScale([0, 4], [360, 16]);
    expect(scale(0)).toBe(360);
    expect(scale(4)).toBe(16);
    expect(scale(2)).toBe(188);
  });

  it('maps a zero-width domain onto the range start instead of dividing by zero', () => {
    const scale = linearScale([3, 3], [0, 100]);
    expect(Number.isFinite(scale(3))).toBe(true);
    expect(scale(3)).toBe(0);
  });

  it('inverts a pixel back to its data value', () => {
    expect(invertScale([0, 10], [0, 100], 40)).toBeCloseTo(4, 10);
    expect(invertScale([0, 4], [360, 16], 188)).toBeCloseTo(2, 10);
  });

  it('picks 1-2-5 stepped ticks inside the bounds', () => {
    expect(niceTicks(0, 9.7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(0, 50)).toEqual([0, 10, 20, 30, 40, 50]);

    const fine = niceTicks(0, 1);
    expect(fine.length).toBe(6);
    fine.forEach((tick, index) => expect(tick).toBeCloseTo(index * 0.2, 10));
  });

  it('keeps every tick within [min, max]', () => {
    for (const [lo, hi] of [[0, 9.7], [-3.2, 4.8], [0.004, 0.031], [17, 1900]]) {
      const ticks = niceTicks(lo, hi);
      expect(ticks.length).toBeGreaterThan(1);
      expect(Math.min(...ticks)).toBeGreaterThanOrEqual(lo);
      expect(Math.max(...ticks)).toBeLessThanOrEqual(hi);
    }
  });

  it('degrades gracefully on flat or non-finite bounds', () => {
    expect(niceTicks(2, 2)).toEqual([2]);
    expect(niceTicks(Number.NaN, 5)).toEqual([]);
  });

  it('pads the data extent and handles empty/flat input', () => {
    expect(extent([0, 10], 0)).toEqual([0, 10]);
    expect(extent([0, 10], 0.1)).toEqual([-1, 11]);
    expect(extent([])).toEqual([0, 1]);
    expect(extent([4, 4])).toEqual([3.5, 4.5]);
  });

  it('scales tick label precision to the axis span', () => {
    expect(tickLabel(120, 400)).toBe('120');
    expect(tickLabel(1.25, 4)).toBe('1.3');
    expect(tickLabel(0.0123, 0.03)).toBe('0.012');
  });
});

describe('ScatterChart', () => {
  function createFixture(fit: { A: number | null; B: number | null } | null) {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ imports: [ScatterChart] });
    const fixture = TestBed.createComponent(ScatterChart);
    fixture.componentRef.setInput('points', SCATTER);
    fixture.componentRef.setInput('fit', fit);
    return fixture;
  }

  it('renders one dot per point plus the fit line', async () => {
    const fixture = createFixture({ A: 146.23, B: -1.87 });
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelectorAll('circle.dot').length).toBe(3);
    expect(host.querySelectorAll('line.fit').length).toBe(1);
    expect(host.textContent).toContain('√PSD, g/√Гц (0.5–6 Гц)');
    expect(host.textContent).toContain('IRI профілометра, м/км');
  });

  it('emits segClick with the seg_id of the clicked dot', async () => {
    const fixture = createFixture({ A: 146.23, B: -1.87 });
    const seen: number[] = [];
    fixture.componentInstance.segClick.subscribe(id => seen.push(id));
    await fixture.whenStable();

    const dots = (fixture.nativeElement as HTMLElement).querySelectorAll('circle.dot');
    (dots[1] as SVGCircleElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await fixture.whenStable();

    expect(seen).toEqual([2]);
  });

  it('enlarges the selected dot', async () => {
    const fixture = createFixture({ A: 146.23, B: -1.87 });
    fixture.componentRef.setInput('selectedSegId', 3);
    await fixture.whenStable();

    const dots = Array.from((fixture.nativeElement as HTMLElement)
      .querySelectorAll('circle.dot'));
    expect(dots.map(dot => dot.getAttribute('r'))).toEqual(['4', '4', '7']);
    expect(dots[2].classList.contains('selected')).toBe(true);
  });

  it('drops the fit line and says so when the fit is degenerate', async () => {
    const fixture = createFixture({ A: null, B: null });
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelectorAll('line.fit').length).toBe(0);
    expect(host.textContent).toContain('фіт вироджений — недоступно');
  });
});

describe('ProfileChart', () => {
  /** jsdom reports a 0x0 box for every element, which would make toChart bail out. */
  function stubBox(svg: SVGSVGElement): void {
    svg.getBoundingClientRect = () => ({
      x: 0, y: 0, left: 0, top: 0, right: CHART_W, bottom: CHART_H,
      width: CHART_W, height: CHART_H, toJSON: () => ({}),
    }) as DOMRect;
  }
  const CHART_W = 640;
  const CHART_H = 400;

  function pointer(target: Element, type: string, clientX: number): void {
    target.dispatchEvent(new PointerEvent(type, {
      clientX, clientY: 200, pointerId: 1, bubbles: true,
    }));
  }

  async function createProfile() {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ imports: [ProfileChart] });
    const fixture = TestBed.createComponent(ProfileChart);
    fixture.componentRef.setInput('points', PROFILE);
    await fixture.whenStable();
    const svg = (fixture.nativeElement as HTMLElement).querySelector('svg')!;
    stubBox(svg);
    const ranges: ([number, number] | null)[] = [];
    fixture.componentInstance.range.subscribe(range => ranges.push(range));
    return { fixture, svg, ranges };
  }

  function band(host: HTMLElement): { x0: number; x1: number } | null {
    const rect = host.querySelector('rect.brush');
    if (!rect) return null;
    const x0 = Number(rect.getAttribute('x'));
    return { x0, x1: x0 + Number(rect.getAttribute('width')) };
  }

  it('renders the three IRI profiles, the corrected one dashed', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ imports: [ProfileChart] });
    const fixture = TestBed.createComponent(ProfileChart);
    fixture.componentRef.setInput('points', PROFILE);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const paths = Array.from(host.querySelectorAll('path'));
    expect(paths.length).toBe(3);
    expect(paths.map(path => path.getAttribute('class')))
      .toEqual(['line-ref', 'line-multi', 'line-corrected']);
    expect(paths[0].getAttribute('d')).toMatch(/^M[\d.]+ [\d.]+( L[\d.]+ [\d.]+){2}$/);
    expect(paths[2].getAttribute('stroke-dasharray')).toBe('6 4');
    expect(host.textContent).toContain('Пікетаж, км');
  });

  it('keeps the drag alive when the pointer leaves and commits it on release', async () => {
    const { fixture, svg, ranges } = await createProfile();
    const host = fixture.nativeElement as HTMLElement;

    pointer(svg, 'pointerdown', 148);
    pointer(svg, 'pointermove', 448);
    await fixture.whenStable();
    expect(band(host)).toEqual({ x0: 148, x1: 448 });

    // pointerleave must drop the crosshair only — the captured drag survives
    svg.dispatchEvent(new PointerEvent('pointerleave', { pointerId: 1 }));
    await fixture.whenStable();
    expect(host.querySelectorAll('line.crosshair').length).toBe(0);
    expect(band(host)).toEqual({ x0: 148, x1: 448 });

    // Pointer capture routes the release back to the SVG: band and filter agree
    pointer(svg, 'pointerup', 448);
    await fixture.whenStable();
    expect(band(host)).toEqual({ x0: 148, x1: 448 });
    expect(ranges.length).toBe(1);
    expect(ranges[0]![0]).toBeCloseTo(0.03472, 4);
    expect(ranges[0]![1]).toBeCloseTo(0.13889, 4);
  });

  it('tracks the band again after the pointer re-enters mid-drag', async () => {
    const { fixture, svg, ranges } = await createProfile();
    const host = fixture.nativeElement as HTMLElement;

    pointer(svg, 'pointerdown', 148);
    pointer(svg, 'pointermove', 448);
    svg.dispatchEvent(new PointerEvent('pointerleave', { pointerId: 1 }));
    pointer(svg, 'pointermove', 348);
    pointer(svg, 'pointerup', 348);
    await fixture.whenStable();

    expect(band(host)).toEqual({ x0: 148, x1: 348 });
    expect(ranges.length).toBe(1);
    expect(ranges[0]![1]).toBeCloseTo(0.10417, 4);
  });

  it('clamps the band and the emitted range to the plot rect', async () => {
    const { fixture, svg, ranges } = await createProfile();
    const host = fixture.nativeElement as HTMLElement;

    pointer(svg, 'pointerdown', -60);
    pointer(svg, 'pointermove', 900);
    pointer(svg, 'pointerup', 900);
    await fixture.whenStable();

    // PLOT.x0 = 48, PLOT.x1 = 624 — never over the axis labels
    expect(band(host)).toEqual({ x0: 48, x1: 624 });
    // and never extrapolated past the chainage extent (0 … 0.2 km)
    expect(ranges[0]![0]).toBeCloseTo(0, 10);
    expect(ranges[0]![1]).toBeCloseTo(0.2, 10);
  });
});

describe('BaChart', () => {
  it('renders the bias line and the two dashed limits of agreement', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ imports: [BaChart] });
    const fixture = TestBed.createComponent(BaChart);
    fixture.componentRef.setInput('points', BA);
    fixture.componentRef.setInput('bias', 1.6);
    fixture.componentRef.setInput('loa', [1.2, 2.0]);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelectorAll('line.bias-line').length).toBe(1);
    const loa = Array.from(host.querySelectorAll('line.loa'));
    expect(loa.length).toBe(2);
    expect(loa.every(line => line.getAttribute('stroke-dasharray') === '6 4')).toBe(true);
    expect(host.querySelectorAll('circle.dot').length).toBe(3);
    expect(host.textContent).toContain('зсув');
    expect(host.textContent).toContain('±1.96σ');
  });
});
