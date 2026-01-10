"""
IRI computation (PSD and multi-linear regression)
Згідно з agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md розділи A2-A3, B5
"""

import numpy as np
from scipy.signal import welch
from typing import Tuple
from enum import Enum


class VehicleType(Enum):
    """Vehicle classification для IRI multi-linear"""
    LEV = "lev"  # Large European Van
    DSD = "dsd"  # D-class Sedan
    GENERIC = "generic"  # Без типу авто


def compute_psd_band_power(
    signal_g: np.ndarray,
    fs: float,
    f_low: float = 0.5,
    f_high: float = 6.0,
    nperseg: int = None,
    scalar_mode: str = 'band_power_sqrt'
) -> Tuple[float, dict]:
    """
    Обчислити band power з PSD (Welch)
    
    Згідно B5:
    - Welch PSD з вікном Hann
    - Band power = sum(PSD * Δf) на діапазоні [f_low, f_high]
    - sqrtPSD залежить від scalar_mode
    
    Args:
        signal_g: сигнал в g (рівномірно дискретизований)
        fs: частота семплювання (Гц)
        f_low, f_high: діапазон частот (Гц)
        nperseg: довжина сегмента для Welch (якщо None, використати fs*4)
        scalar_mode: режим скаляризації ('band_power_sqrt', 'mean_psd_sqrt', 
                     'median_psd_sqrt', 'peak_psd_sqrt')
        
    Returns:
        (sqrtPSD, debug_info)
        sqrtPSD: скаляр залежно від scalar_mode
        debug_info: dict з діагностичною інформацією
    """
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
        debug_info = {
            'psd_band_power': 0.0,
            'psd_sqrt_scalar': 0.0,
            'psd_scalar_mode': scalar_mode,
            'psd_n_samples_used': len(signal_g),
            'psd_df_hz': 0.0,
            'psd_freqs_n': len(freqs),
            'psd_band_n': 0
        }
        return 0.0, debug_info
    
    df = freqs[1] - freqs[0]
    psd_band = psd[idx_band]
    band_power = np.sum(psd_band) * df
    
    # Різні режими скаляризації
    if scalar_mode == 'band_power_sqrt':
        sqrtPSD = np.sqrt(band_power)
    elif scalar_mode == 'mean_psd_sqrt':
        sqrtPSD = np.sqrt(np.mean(psd_band))
    elif scalar_mode == 'median_psd_sqrt':
        sqrtPSD = np.sqrt(np.median(psd_band))
    elif scalar_mode == 'peak_psd_sqrt':
        sqrtPSD = np.sqrt(np.max(psd_band))
    else:
        sqrtPSD = np.sqrt(band_power)  # fallback
    
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
    scalar_mode: str = 'band_power_sqrt',
    return_debug: bool = False
) -> Tuple[float, float, dict]:
    """
    Обчислити IRI з PSD (Eq.3)
    
    Згідно A2-A3:
    IRI = 0.774 * sqrt(PSD) - 0.825
    
    де sqrt(PSD) залежить від scalar_mode
    
    Args:
        a_vertical_g: вертикальне прискорення в g (після фільтрації та distress removal)
        fs: частота семплювання (Гц)
        f_low, f_high: діапазон частот для band-pass
        scalar_mode: режим скаляризації PSD
        return_debug: повертати debug інформацію
        
    Returns:
        (iri_psd_raw, iri_psd, debug_info)
        iri_psd_raw: сире значення з Eq.3 (може бути негативним)
        iri_psd: clipped версія (>= 0)
        debug_info: dict з діагностикою (якщо return_debug=True)
    """
    sqrtPSD, debug_info = compute_psd_band_power(
        a_vertical_g, fs, f_low, f_high, scalar_mode=scalar_mode
    )
    
    # Eq.3 з книги (КОЕФІЦІЄНТИ НЕ ЗМІНЮВАТИ!)
    iri_psd_raw = 0.774 * sqrtPSD - 0.825
    
    # Clipped версія
    iri_psd = max(0.0, iri_psd_raw)
    
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
    Обчислити IRI через мультиваріантну лінійну регресію (Eq.4/5/6)
    
    Згідно A3:
    
    Eq.4 (LEV):
    IRI = 55.25·Grms - 0.07·Speed + 0.19·Npeop - 2.93·Stif - 1.09·DampF - 1.44·TyreS + 7.66
    
    Eq.5 (DSD):
    IRI = 54.43·Grms - 0.06·Speed + 0.18·Npeop - 0.87·Stif - 0.89·DampF - 0.27·TyreS + 5.75
    
    Eq.6 (GENERIC):
    IRI = 50.32·Grms - 0.06·Speed + 0.17·Npeop - 1.86·Stif - 0.90·DampF - 0.78·TyreS + 6.68
    
    Args:
        grms: Grms (скаляр)
        speed_kmh: середня швидкість на сегменті (км/год)
        npeop: кількість людей / вага пасажирів (1..4, 70 кг/людина)
        stif: коефіцієнт жорсткості (0.8, 1.0, 1.2)
        dampf: коефіцієнт демпфування (0.8, 1.0, 1.2)
        tyres: коефіцієнт шин (0.7, 0.9, 1.0)
        vehicle_type: тип авто (LEV/DSD/GENERIC)
        
    Returns:
        IRI: International Roughness Index (m/km)
    """
    if vehicle_type == VehicleType.LEV:
        # Eq.4
        IRI = (55.25 * grms 
               - 0.07 * speed_kmh 
               + 0.19 * npeop 
               - 2.93 * stif 
               - 1.09 * dampf 
               - 1.44 * tyres 
               + 7.66)
    elif vehicle_type == VehicleType.DSD:
        # Eq.5
        IRI = (54.43 * grms 
               - 0.06 * speed_kmh 
               + 0.18 * npeop 
               - 0.87 * stif 
               - 0.89 * dampf 
               - 0.27 * tyres 
               + 5.75)
    else:  # GENERIC
        # Eq.6
        IRI = (50.32 * grms 
               - 0.06 * speed_kmh 
               + 0.17 * npeop 
               - 1.86 * stif 
               - 0.90 * dampf 
               - 0.78 * tyres 
               + 6.68)
    
    # IRI не може бути від'ємним
    return max(0.0, IRI)
