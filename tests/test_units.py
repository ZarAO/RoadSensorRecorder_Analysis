"""
Unit test для перевірки одиниць вимірювання
"""

import pytest
import numpy as np
from road_quality_analyzer.metrics.iri import compute_iri_psd
from road_quality_analyzer.metrics.grms import compute_grms
from road_quality_analyzer.anomaly.threshold import detect_threshold_anomalies


def test_units_grms():
    """
    Перевірка: Grms рахується на a_vertical в g
    """
    g0 = 9.80665  # м/с²
    
    # Вертикальне прискорення в м/с²
    a_vertical_ms2 = np.array([1.0, 2.0, 3.0])
    
    # Конвертувати в g
    a_vertical_g = a_vertical_ms2 / g0
    
    # Grms має бути в g
    grms = compute_grms(a_vertical_g)
    
    # Очікуване: sqrt(mean([1/g0, 2/g0, 3/g0]^2)) = sqrt(mean([0.102, 0.204, 0.306]^2))
    expected_grms = np.sqrt(np.mean(a_vertical_g**2))
    
    assert grms == pytest.approx(expected_grms, abs=1e-6)
    assert grms < 1.0  # має бути в g, тобто малий


def test_units_threshold_anomaly():
    """
    Перевірка: threshold 10 м/с² працює на a_vertical в м/с²
    """
    # Вертикальне прискорення в м/с²
    a_vertical_ms2 = np.array([5.0, 8.0, 12.0, 15.0, 3.0])
    
    # Threshold має працювати в м/с²
    anomalies = detect_threshold_anomalies(a_vertical_ms2, threshold_ms2=10.0)
    
    # Очікуємо аномалії для 12.0 та 15.0
    expected = np.array([False, False, True, True, False])
    
    np.testing.assert_array_equal(anomalies, expected)


def test_units_iri_psd_input():
    """
    Перевірка: IRI_psd приймає a_vertical в g
    
    Примітка: цей тест перевіряє тільки що функція працює з правильними одиницями,
    а не що результат реалістичний (це залежить від даних)
    """
    g0 = 9.80665
    fs = 100.0
    
    # Синтетичний сигнал: синус 3 Hz з амплітудою 0.5 м/с²
    t = np.linspace(0, 10, 1000)
    a_vertical_ms2 = 0.5 * np.sin(2 * np.pi * 3.0 * t)
    
    # Конвертувати в g
    a_vertical_g = a_vertical_ms2 / g0
    
    # IRI_psd має приймати в g
    iri_psd_raw, iri_psd, debug = compute_iri_psd(
        a_vertical_g, fs, return_debug=True
    )
    
    # Перевіряємо що sqrtPSD обчислено
    assert 'psd_sqrt_scalar' in debug
    assert debug['psd_sqrt_scalar'] >= 0
    
    # Перевіряємо що a_vertical був в g (типові значення < 1)
    assert np.max(np.abs(a_vertical_g)) < 1.0
    
    # IRI_psd_raw може бути негативним (нормально для малих PSD)
    # але має бути числом
    assert isinstance(iri_psd_raw, (int, float, np.number))
    assert isinstance(iri_psd, (int, float, np.number))


def test_psd_scalar_modes_consistency():
    """
    Перевірка: різні scalar_mode дають різні, але валідні результати
    """
    fs = 100.0
    t = np.linspace(0, 10, 1000)
    
    # Сигнал з кількома частотами
    a_vertical_g = (
        0.01 * np.sin(2 * np.pi * 1.0 * t) +
        0.02 * np.sin(2 * np.pi * 3.0 * t) +
        0.01 * np.sin(2 * np.pi * 5.0 * t)
    )
    
    modes = ['band_power_sqrt', 'mean_psd_sqrt', 'median_psd_sqrt', 'peak_psd_sqrt']
    results = {}
    
    for mode in modes:
        iri_raw, iri, debug = compute_iri_psd(
            a_vertical_g, fs, scalar_mode=mode, return_debug=True
        )
        results[mode] = {
            'iri_raw': iri_raw,
            'iri': iri,
            'sqrt_psd': debug['psd_sqrt_scalar']
        }
    
    # Всі результати мають бути числами
    for mode, res in results.items():
        assert isinstance(res['iri_raw'], (int, float, np.number))
        assert isinstance(res['iri'], (int, float, np.number))
        assert res['sqrt_psd'] >= 0
    
    # peak_psd_sqrt має давати найбільший sqrtPSD
    assert results['peak_psd_sqrt']['sqrt_psd'] >= results['median_psd_sqrt']['sqrt_psd']
    assert results['median_psd_sqrt']['sqrt_psd'] >= 0
