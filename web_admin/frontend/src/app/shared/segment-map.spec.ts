import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ThemeService } from '../theme.service';
import { SegmentMap, escapeHtml, segmentColor } from './segment-map';

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

  it('reads props[metricKey] when a metricKey is given', () => {
    expect(segmentColor({ iri_ref: 7 }, 'iri_ref')).toBe('#d81e2c');
    expect(segmentColor({ iri_ref: 1 }, 'iri_ref')).toBe('#00a63e');
    // iri_multi present but metricKey is iri_ref: must not fall back to it
    expect(segmentColor({ iri_multi: 7, iri_ref: 1 }, 'iri_ref')).toBe('#00a63e');
  });

  it('defaults to iri_multi when no metricKey is given', () => {
    expect(segmentColor({ iri_multi: 7 })).toBe('#d81e2c');
  });

  it('still marks class-1/2 survey magenta first with a non-default metricKey', () => {
    expect(segmentColor({ needs_class12_survey: true, iri_ref: 1 }, 'iri_ref')).toBe('#FF00FF');
  });
});

describe('escapeHtml', () => {
  it('neutralizes markup coming from a geojson filename', () => {
    expect(escapeHtml('<img src=x onerror=alert(1)>'))
      .toBe('&lt;img src=x onerror=alert(1)&gt;');
    expect(escapeHtml(`a&b "q" 'p'`)).toBe('a&amp;b &quot;q&quot; &#39;p&#39;');
  });

  it('leaves a plain filename untouched', () => {
    expect(escapeHtml('drive_2026-08-20.csv')).toBe('drive_2026-08-20.csv');
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
