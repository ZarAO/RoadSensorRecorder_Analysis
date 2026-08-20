"""
Publication-grade figures for the validation study (scienceplots, PDF+PNG).
Axis labels in Ukrainian (dissertation language), units always present.
"""

from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scienceplots  # noqa: F401 (registers the styles)

plt.style.use(['science', 'no-latex'])

ROAD_MARKERS = {'М-03': ('o', '#2166ac'), 'Т1016': ('s', '#b2182b')}
DPI = 300


def _save(fig, out_dir: Path, name: str) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ('pdf', 'png'):
        p = out_dir / f'{name}.{ext}'
        fig.savefig(p, dpi=DPI, bbox_inches='tight')
        paths.append(str(p))
    plt.close(fig)
    return paths


def scatter_fit(pairs: pd.DataFrame, fit: dict, out_dir: Path) -> list:
    """sqrtPSD -> IRI_ref scatter per road with the pooled OLS line."""
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    for road, group in pairs.groupby('road'):
        marker, color = ROAD_MARKERS.get(road, ('^', 'gray'))
        ax.scatter(group['psd_sqrt_scalar'], group['iri_ref'],
                   s=14, alpha=0.65, marker=marker, color=color,
                   label=f'{road} (n={len(group)})', edgecolors='none')
    x = np.linspace(pairs['psd_sqrt_scalar'].min(), pairs['psd_sqrt_scalar'].max(), 50)
    ax.plot(x, fit['A'] * x + fit['B'], 'k-', linewidth=1.2,
            label=f"IRI = {fit['A']:.2f}·√PSD {fit['B']:+.2f}  (R²={fit['r2']:.2f})")
    ax.set_xlabel(r'$\sqrt{\mathrm{PSD}}$, g/$\sqrt{\mathrm{Hz}}$ (смуга 0.5–6 Гц)')
    ax.set_ylabel('IRI профілометра, м/км')
    ax.legend(fontsize=7)
    return _save(fig, out_dir, 'fig1_scatter_eq3_fit')


def bland_altman_plot(pairs: pd.DataFrame, metric_col: str, title: str,
                      out_dir: Path, name: str) -> list:
    diff = pairs[metric_col] - pairs['iri_ref']
    mean = (pairs[metric_col] + pairs['iri_ref']) / 2.0
    bias = float(diff.mean())
    sd = float(diff.std(ddof=1))
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    for road, group_idx in pairs.groupby('road').groups.items():
        marker, color = ROAD_MARKERS.get(road, ('^', 'gray'))
        ax.scatter(mean.loc[group_idx], diff.loc[group_idx], s=14, alpha=0.65,
                   marker=marker, color=color, label=road, edgecolors='none')
    ax.axhline(bias, color='k', linewidth=1.0, label=f'зсув = {bias:+.2f} м/км')
    for limit in (bias - 1.96 * sd, bias + 1.96 * sd):
        ax.axhline(limit, color='k', linewidth=0.8, linestyle='--')
    ax.set_xlabel('Середнє двох методів, м/км')
    ax.set_ylabel('Різниця (смартфон − профілометр), м/км')
    ax.set_title(title, fontsize=8)
    ax.legend(fontsize=7)
    return _save(fig, out_dir, name)


def chainage_overlay(pairs: pd.DataFrame, road: str, out_dir: Path,
                     calibrated_col: str = 'iri_calibrated') -> list:
    """Profilometer vs calibrated smartphone IRI along the chainage of one road."""
    df = pairs[pairs['road'] == road].sort_values('chainage_m')
    km = df['chainage_m'] / 1000.0
    fig, ax = plt.subplots(figsize=(5.4, 2.8))
    ax.plot(km, df['iri_ref'], '-', color='#333333', linewidth=1.1,
            label='Профілометр (сер. кан. 1–8)')
    ax.plot(km, df[calibrated_col], '-', color=ROAD_MARKERS.get(road, ('o', 'tab:blue'))[1],
            linewidth=1.1, alpha=0.85, label='Смартфон (калібр. Eq.3)')
    ax.set_xlabel('Пікетаж, км')
    ax.set_ylabel('IRI, м/км')
    ax.set_title(road, fontsize=8)
    ax.legend(fontsize=7)
    return _save(fig, out_dir, f'fig3_chainage_{road.replace("-", "").replace("М", "M").replace("Т", "T")}')
