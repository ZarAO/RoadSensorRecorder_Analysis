import {
  Component, DestroyRef, ElementRef, afterNextRender, effect, inject, input, output,
  signal, untracked, viewChild,
} from '@angular/core';
import * as L from 'leaflet';

import { GeoJsonFeatureCollection } from '../api/dto';
import { ThemeService } from '../theme.service';

/**
 * IRI_multi severity scale — a data-visualization contract shared by every map,
 * not a UI theme token (hence the raw hexes). #FF00FF keeps marking class-1/2
 * segments, which never carry a numeric IRI at all.
 */
const IRI_SCALE = {
  good: '#00a63e',
  fair: '#f5c400',
  poor: '#ff7300',
  bad: '#d81e2c',
  survey: '#FF00FF',
  unknown: '#8b93a3',
} as const;

/** The IRI-shaped metric a map colors and labels segments/intervals by. */
export type SegmentMetricKey = 'iri_multi' | 'iri_ref';

/** Severity color for props[metricKey]; the class-1/2 magenta wins over any IRI value. */
export function segmentColor(
  props: Record<string, unknown>, metricKey: SegmentMetricKey = 'iri_multi',
): string {
  if (props['needs_class12_survey']) return IRI_SCALE.survey;
  const iri = props[metricKey];
  if (typeof iri !== 'number') return IRI_SCALE.unknown;
  if (iri < 2.5) return IRI_SCALE.good;
  if (iri < 4) return IRI_SCALE.fair;
  if (iri < 6) return IRI_SCALE.poor;
  return IRI_SCALE.bad;
}

const LEGEND: ReadonlyArray<{ color: string; label: string }> = [
  { color: IRI_SCALE.good, label: '< 2.5' },
  { color: IRI_SCALE.fair, label: '2.5–4' },
  { color: IRI_SCALE.poor, label: '4–6' },
  { color: IRI_SCALE.bad, label: '≥ 6' },
  { color: IRI_SCALE.survey, label: 'Потребує обстеження профілометром (клас 1/2)' },
  { color: IRI_SCALE.unknown, label: 'IRI недоступний' },
];

// Theme-matched basemaps (CARTO, free with attribution)
const TILES = {
  dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
};
const TILE_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>';

/** Casing is drawn in the inverse of the basemap so every hue stays readable. */
const CASING = { dark: 'rgba(245,245,244,0.9)', light: 'rgba(15,18,25,0.85)' };

/** Popup HTML is built by hand, so any value coming from a geojson property
 *  (filename) is escaped before interpolation. */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const CASING_WEIGHT = 10;
const LINE_WEIGHT = 6;
const LINE_HOVER_WEIGHT = 9;
const LINE_OPACITY = 0.95;
const DEFAULT_CENTER: L.LatLngTuple = [50.45, 30.52];
const DEFAULT_ZOOM = 11;

@Component({
  selector: 'app-segment-map',
  template: `
    <div #canvas class="map-canvas" role="application"
         aria-label="Мапа сегментів дороги"></div>
    <div class="legend" aria-label="Легенда IRI">
      @for (item of legend; track item.color) {
        <span class="legend-item"><i [style.background]="item.color"></i> {{ item.label }}</span>
      }
    </div>
  `,
  styles: `
    :host { display: block; position: relative; }

    .map-canvas {
      position: absolute;
      inset: 0;
      background: var(--color-bg);
    }

    .legend {
      position: absolute;
      z-index: 1000;
      right: var(--space-4);
      bottom: var(--space-4);
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-4);
      max-width: 30rem;
      padding: var(--space-3) var(--space-4);
      background: var(--map-panel-bg);
      backdrop-filter: blur(8px);
      border: 1px solid var(--color-border);
      border-radius: var(--card-radius);
      box-shadow: var(--elevation-overlay);
      font-size: var(--text-xs);
      color: var(--color-muted-fg);
    }
    .legend i {
      display: inline-block;
      width: 0.75rem;
      height: 0.75rem;
      border-radius: var(--radius-sm);
      margin-right: var(--space-1);
      vertical-align: -1px;
    }

    /* Leaflet chrome follows the theme */
    :host ::ng-deep .leaflet-popup-content-wrapper,
    :host ::ng-deep .leaflet-popup-tip {
      background: var(--color-surface-raised);
      color: var(--color-fg);
      box-shadow: var(--elevation-overlay);
    }
    :host ::ng-deep .leaflet-popup-content a { color: var(--color-accent); }
    :host ::ng-deep .leaflet-bar a {
      background: var(--color-surface-raised);
      color: var(--color-fg);
      border-color: var(--color-border);
    }
    :host ::ng-deep .leaflet-bar a:hover { background: var(--color-surface-hover); }

    @media (max-width: 720px) {
      .legend { left: var(--space-4); max-width: none; }
    }
  `,
})
export class SegmentMap {
  readonly data = input<GeoJsonFeatureCollection | null>(null);
  /** Global map: the popup offers a link to the owning run. */
  readonly showRunLink = input(false);
  /** Which property drives color + popup value: run segments (iri_multi,
   *  default) or reference intervals (iri_ref). */
  readonly metricKey = input<SegmentMetricKey>('iri_multi');
  readonly runClick = output<number>();

  readonly legend = LEGEND;

  private readonly themeService = inject(ThemeService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly canvas = viewChild.required<ElementRef<HTMLDivElement>>('canvas');

  private readonly ready = signal(false);
  private map: L.Map | null = null;
  private tiles: L.TileLayer | null = null;
  private casing: L.GeoJSON | null = null;
  private line: L.GeoJSON | null = null;
  private fitted = false;

  constructor() {
    // Leaflet needs a laid-out container; vitest/jsdom never reaches this hook.
    afterNextRender(() => {
      this.map = L.map(this.canvas().nativeElement, { zoomControl: false })
        .setView(DEFAULT_CENTER, DEFAULT_ZOOM);
      L.control.zoom({ position: 'bottomleft' }).addTo(this.map);
      this.ready.set(true);
    });
    this.destroyRef.onDestroy(() => this.map?.remove());

    // Basemap and casing are both theme-inverse: they flip together
    effect(() => {
      const theme = this.themeService.theme();
      if (!this.ready() || !this.map) return;
      this.tiles?.remove();
      this.tiles = L.tileLayer(TILES[theme], { attribution: TILE_ATTR }).addTo(this.map);
      this.casing?.setStyle({ color: CASING[theme] });
    });

    effect(() => {
      const fc = this.data();
      const metricKey = this.metricKey();
      if (!this.ready()) return;
      this.render(fc, metricKey);
    });
  }

  private render(fc: GeoJsonFeatureCollection | null, metricKey: SegmentMetricKey): void {
    const map = this.map;
    if (!map) return;
    this.casing?.remove();
    this.line?.remove();
    this.casing = null;
    this.line = null;
    if (!fc || fc.features.length === 0) return;

    const casingColor = untracked(() => CASING[this.themeService.theme()]);
    // Casing goes in first so the data line paints on top of it
    this.casing = L.geoJSON(fc as never, {
      interactive: false,
      // Short segments come out as Points; keep them paths, not default pins
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 7 }),
      style: () => ({ color: casingColor, weight: CASING_WEIGHT, opacity: 1 }),
    }).addTo(map);

    this.line = L.geoJSON(fc as never, {
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 4 }),
      style: feature => ({
        color: segmentColor(feature?.properties ?? {}, metricKey),
        weight: LINE_WEIGHT,
        opacity: LINE_OPACITY,
      }),
      onEachFeature: (feature, layer) => {
        const props: Record<string, unknown> = feature.properties ?? {};
        const path = layer as L.Path;
        path.on('mouseover', () => path.setStyle({ weight: LINE_HOVER_WEIGHT, opacity: 1 }));
        path.on('mouseout', () =>
          path.setStyle({ weight: LINE_WEIGHT, opacity: LINE_OPACITY }));
        layer.bindPopup(this.popupHtml(props, metricKey));
        layer.on('popupopen', event => {
          const link = event.popup.getElement()?.querySelector('a[data-run]');
          link?.addEventListener('click', clickEvent => {
            clickEvent.preventDefault();
            this.runClick.emit(Number(props['run_id']));
          });
        });
      },
    }).addTo(map);

    if (!this.fitted) {
      const bounds = this.line.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40] });
        this.fitted = true;
      }
    }
  }

  private popupHtml(props: Record<string, unknown>, metricKey: SegmentMetricKey): string {
    const runId = props['run_id'];
    // filename/run_id exist only on the merged global map, not in a run's own geojson
    const title = props['filename'] != null
      ? `<b>${escapeHtml(String(props['filename']))}</b><br>`
      : '';
    const runLink = this.showRunLink() && runId != null
      ? `<br><a href="#" data-run="${runId}">До рану #${runId}</a>`
      : '';
    if (props['seg_id'] != null) {
      return `${title}Сегмент ${props['seg_id']}, IRI_multi: ${this.iriLabel(props)}${runLink}`;
    }
    if (props['interval_id'] != null) {
      return `Інтервал ${props['interval_id']}, IRI: ${this.metricLabel(props, metricKey)}`;
    }
    return `${title}${runLink}`;
  }

  private metricLabel(props: Record<string, unknown>, metricKey: SegmentMetricKey): string {
    const value = props[metricKey];
    return typeof value === 'number' ? value.toFixed(2) : '—';
  }

  /** Low-speed invariant: a class-1/2 segment never shows a number */
  private iriLabel(props: Record<string, unknown>): string {
    if (props['needs_class12_survey']) return '— (клас 1/2)';
    const iri = props['iri_multi'];
    return typeof iri === 'number' ? iri.toFixed(2) : '—';
  }
}
