import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ThemeService } from '../theme.service';
import { SegmentMap, segmentColor } from './segment-map';

describe('segmentColor', () => {
  it('maps IRI_multi onto the severity scale', () => {
    expect(segmentColor({ iri_multi: 0 })).toBe('#00a63e');
    expect(segmentColor({ iri_multi: 2.4 })).toBe('#00a63e');
    expect(segmentColor({ iri_multi: 2.5 })).toBe('#f5c400');
    expect(segmentColor({ iri_multi: 3.9 })).toBe('#f5c400');
    expect(segmentColor({ iri_multi: 4 })).toBe('#ff7300');
    expect(segmentColor({ iri_multi: 5.9 })).toBe('#ff7300');
    expect(segmentColor({ iri_multi: 6 })).toBe('#d81e2c');
    expect(segmentColor({ iri_multi: 12.5 })).toBe('#d81e2c');
  });

  it('marks class-1/2 survey segments magenta whatever the IRI says', () => {
    expect(segmentColor({ needs_class12_survey: true, iri_multi: 1.1 })).toBe('#FF00FF');
    expect(segmentColor({ needs_class12_survey: true, iri_multi: null })).toBe('#FF00FF');
    expect(segmentColor({ needs_class12_survey: true })).toBe('#FF00FF');
  });

  it('falls back to the no-data gray when IRI is not a number', () => {
    expect(segmentColor({})).toBe('#8b93a3');
    expect(segmentColor({ iri_multi: null })).toBe('#8b93a3');
    expect(segmentColor({ iri_multi: '3.2' })).toBe('#8b93a3');
  });
});

describe('SegmentMap', () => {
  function createFixture() {
    TestBed.configureTestingModule({
      imports: [SegmentMap],
      providers: [
        { provide: ThemeService, useValue: { theme: signal('dark') } },
      ],
    });
    return TestBed.createComponent(SegmentMap);
  }

  it('renders the map host and the six-entry legend', async () => {
    const fixture = createFixture();
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.map-canvas')).toBeTruthy();

    const entries = host.querySelectorAll('.legend .legend-item');
    expect(entries.length).toBe(6);
    expect(host.textContent).toContain('Потребує обстеження профілометром (клас 1/2)');
    expect(host.textContent).toContain('IRI недоступний');
  });

  it('paints every legend swatch with its contract color', async () => {
    const fixture = createFixture();
    await fixture.whenStable();

    const swatches = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.legend i'));
    const colors = swatches.map(swatch => swatch.style.background);
    expect(colors).toEqual([
      'rgb(0, 166, 62)', 'rgb(245, 196, 0)', 'rgb(255, 115, 0)',
      'rgb(216, 30, 44)', 'rgb(255, 0, 255)', 'rgb(139, 147, 163)',
    ]);
  });
});
