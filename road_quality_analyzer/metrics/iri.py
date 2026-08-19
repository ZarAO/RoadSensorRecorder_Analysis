"""
IRI computation (PSD and multi-linear regression)
Sections A2-A3, B5 - IRI calculation
"""

import numpy as np
from scipy.signal import welch
from typing import Tuple
from enum import Enum


class VehicleType(Enum):
    """Vehicle classification for IRI multi-linear"""
    LEV = "lev"  # Large European Van
    DSD = "dsd"  # D-class Sedan
    GENERIC = "generic"  # No specific vehicle type


# Equation coefficients from the book. DO NOT RETUNE for the dataset.
# The report (cli.py) prints exactly these constants, so they are the single source of truth.
IRI_PSD_COEFFICIENTS = {
    'A_sqrt_psd': 0.774,
    'B_const': -0.825,
}

IRI_MULTI_COEFFICIENTS = {
    # Eq.4
    VehicleType.LEV: {
        'grms': 55.25, 'speed_kmh': -0.07, 'npeop': 0.19,
        'stif': -2.93, 'dampf': -1.09, 'tyres': -1.44, 'const': 7.66,
    },
    # Eq.5
    VehicleType.DSD: {
        'grms': 54.43, 'speed_kmh': -0.06, 'npeop': 0.18,
        'stif': -0.87, 'dampf': -0.89, 'tyres': -0.27, 'const': 5.75,
    },
    # Eq.6
    VehicleType.GENERIC: {
        'grms': 50.32, 'speed_kmh': -0.06, 'npeop': 0.17,
        'stif': -1.86, 'dampf': -0.90, 'tyres': -0.78, 'const': 6.68,
    },
}

# Vehicle parameters the pipeline uses to call Eq.4/5/6 (not measured)
IRI_MULTI_DEFAULT_PARAMS = {
    'npeop': 1.0,
    'stif': 1.0,
    'dampf': 1.0,
    'tyres': 1.0,
}


def _nan_psd_debug(scalar_mode: str, n_samples: int, freqs_n: int, band_n: int) -> dict:
    """Debug fields for when PSD cannot be computed (NaN, not 0.0)"""
    return {
        'psd_band_power': np.nan,
        'psd_sqrt_scalar': np.nan,
        'psd_scalar_mode': scalar_mode,
        'psd_n_samples_used': n_samples,
        'psd_df_hz': np.nan,
        'psd_freqs_n': freqs_n,
        'psd_band_n': band_n,
    }


def compute_psd_band_power(
    signal_g: np.ndarray,
    fs: float,
    f_low: float = 0.5,
    f_high: float = 6.0,
    nperseg: int = None,
    scalar_mode: str = 'mean_psd_sqrt'
) -> Tuple[float, dict]:
    """
    Compute the PSD scalar (Welch)

    Per B5:
    - Welch PSD with a Hann window
    - Band power = sum(PSD * Δf) over [f_low, f_high]
    - sqrtPSD depends on scalar_mode

    Units: psd - g²/Hz, band_power - g², mean/median/peak psd - g²/Hz.
    Eq.3 needs the density itself (g/√Hz), so the default is 'mean_psd_sqrt'.

    Args:
        signal_g: signal in g (uniformly sampled)
        fs: sampling rate (Hz)
        f_low, f_high: frequency range (Hz)
        nperseg: Welch segment length (if None, use fs*4)
        scalar_mode: scalarization mode ('mean_psd_sqrt', 'band_power_sqrt',
                     'median_psd_sqrt', 'peak_psd_sqrt')

    Returns:
        (sqrtPSD, debug_info)
        sqrtPSD: scalar depending on scalar_mode, NaN if PSD cannot be computed
        debug_info: dict with diagnostic information
    """
    # Welch needs at least 2 seconds of signal, otherwise NaN, not a made-up number
    if len(signal_g) < fs * 2:
        return np.nan, _nan_psd_debug(scalar_mode, len(signal_g), 0, 0)

    if nperseg is None:
        nperseg = min(len(signal_g), int(fs * 4))

    # Welch PSD
    freqs, psd = welch(
        signal_g,
        fs=fs,
        window='hann',
        nperseg=nperseg,
        noverlap=nperseg // 2
    )

    # Band power
    idx_band = (freqs >= f_low) & (freqs <= f_high)
    n_band = np.sum(idx_band)

    if n_band == 0:
        return np.nan, _nan_psd_debug(scalar_mode, len(signal_g), len(freqs), 0)

    df = freqs[1] - freqs[0]
    psd_band = psd[idx_band]
    band_power = np.sum(psd_band) * df
    
    # Different scalarization modes
    if scalar_mode == 'mean_psd_sqrt':
        sqrtPSD = np.sqrt(np.mean(psd_band))
    elif scalar_mode == 'band_power_sqrt':
        sqrtPSD = np.sqrt(band_power)
    elif scalar_mode == 'median_psd_sqrt':
        sqrtPSD = np.sqrt(np.median(psd_band))
    elif scalar_mode == 'peak_psd_sqrt':
        sqrtPSD = np.sqrt(np.max(psd_band))
    else:
        raise ValueError(f"Unknown scalar_mode: {scalar_mode}")
    
    debug_info = {
        'psd_band_power': band_power,
        'psd_sqrt_scalar': sqrtPSD,
        'psd_scalar_mode': scalar_mode,
        'psd_n_samples_used': len(signal_g),
        'psd_df_hz': df,
        'psd_freqs_n': len(freqs),
        'psd_band_n': n_band
    }
    
    return sqrtPSD, debug_info


def compute_iri_psd(
    a_vertical_g: np.ndarray,
    fs: float,
    f_low: float = 0.5,
    f_high: float = 6.0,
    scalar_mode: str = 'mean_psd_sqrt',
    return_debug: bool = False
) -> Tuple[float, float, dict]:
    """
    Compute IRI from PSD (Eq.3)

    Per A2-A3:
    IRI = 0.774 * sqrt(PSD) - 0.825

    The book's Eq.3 takes the sqrt of the PSD density (g²/Hz -> g/√Hz), so by
    default the scalar is the sqrt of the mean density in the band, not the sqrt
    of the integrated power (which has units of g).

    Args:
        a_vertical_g: vertical acceleration in g (after band-pass filtering and
                      distress removal; must be one contiguous NaN-free run -
                      Welch assumes uniform sampling, so chunks spliced across a
                      removed window would inject broadband energy)
        fs: sampling rate (Hz)
        f_low, f_high: frequency range for the band-pass
        scalar_mode: PSD scalarization mode
        return_debug: whether to return debug information

    Returns:
        (iri_psd_raw, iri_psd, debug_info)
        iri_psd_raw: raw value from Eq.3 (can be negative), NaN if PSD
                     cannot be computed
        iri_psd: clipped version (>= 0), NaN if PSD cannot be computed
        debug_info: dict with diagnostics (if return_debug=True)
    """
    sqrtPSD, debug_info = compute_psd_band_power(
        a_vertical_g, fs, f_low, f_high, scalar_mode=scalar_mode
    )

    # Eq.3 from the book (DO NOT CHANGE THE COEFFICIENTS!)
    iri_psd_raw = (IRI_PSD_COEFFICIENTS['A_sqrt_psd'] * sqrtPSD
                   + IRI_PSD_COEFFICIENTS['B_const'])

    # Clipped version (NaN is not converted to 0: max() would hide a missing value)
    iri_psd = max(0.0, iri_psd_raw) if np.isfinite(iri_psd_raw) else np.nan

    debug_info['iri_psd_raw'] = iri_psd_raw
    debug_info['iri_psd'] = iri_psd
    
    if return_debug:
        return iri_psd_raw, iri_psd, debug_info
    else:
        return iri_psd_raw, iri_psd, {}


def compute_iri_multi(
    grms: float,
    speed_kmh: float,
    npeop: float = 1.0,
    stif: float = 1.0,
    dampf: float = 1.0,
    tyres: float = 1.0,
    vehicle_type: VehicleType = VehicleType.GENERIC
) -> float:
    """
    Compute IRI via multivariate linear regression (Eq.4/5/6)

    Per A3:

    Eq.4 (LEV):
    IRI = 55.25·Grms - 0.07·Speed + 0.19·Npeop - 2.93·Stif - 1.09·DampF - 1.44·TyreS + 7.66

    Eq.5 (DSD):
    IRI = 54.43·Grms - 0.06·Speed + 0.18·Npeop - 0.87·Stif - 0.89·DampF - 0.27·TyreS + 5.75

    Eq.6 (GENERIC):
    IRI = 50.32·Grms - 0.06·Speed + 0.17·Npeop - 1.86·Stif - 0.90·DampF - 0.78·TyreS + 6.68

    Args:
        grms: Grms (scalar)
        speed_kmh: mean speed over the segment (km/h)
        npeop: number of people / passenger weight (1..4, 70 kg/person)
        stif: stiffness coefficient (0.8, 1.0, 1.2)
        dampf: damping coefficient (0.8, 1.0, 1.2)
        tyres: tire coefficient (0.7, 0.9, 1.0)
        vehicle_type: vehicle type (LEV/DSD/GENERIC)

    Returns:
        IRI: International Roughness Index (m/km)
    """
    coeffs = IRI_MULTI_COEFFICIENTS[vehicle_type]

    IRI = (coeffs['grms'] * grms
           + coeffs['speed_kmh'] * speed_kmh
           + coeffs['npeop'] * npeop
           + coeffs['stif'] * stif
           + coeffs['dampf'] * dampf
           + coeffs['tyres'] * tyres
           + coeffs['const'])

    # IRI cannot be negative
    return max(0.0, IRI)
