"""
Grms computation (RMS of vertical acceleration in g)
Section B4 - RMS acceleration
"""

import numpy as np


def compute_grms(a_vertical_g: np.ndarray) -> float:
    """
    Compute Grms (RMS of vertical acceleration in g)

    Per B4:
    Grms = sqrt(mean(a_vertical_g^2))

    Args:
        a_vertical_g: vertical acceleration in g

    Returns:
        Grms: RMS value (scalar)
    """
    return np.sqrt(np.mean(a_vertical_g**2))
