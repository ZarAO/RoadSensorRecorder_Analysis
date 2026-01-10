"""
Grms computation (RMS вертикального прискорення в g)
Згідно з agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md розділ B4
"""

import numpy as np


def compute_grms(a_vertical_g: np.ndarray) -> float:
    """
    Обчислити Grms (RMS вертикального прискорення в g)
    
    Згідно B4:
    Grms = sqrt(mean(a_vertical_g^2))
    
    Args:
        a_vertical_g: вертикальне прискорення в g
        
    Returns:
        Grms: RMS значення (скаляр)
    """
    return np.sqrt(np.mean(a_vertical_g**2))
