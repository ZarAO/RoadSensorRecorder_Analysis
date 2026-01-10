"""
Orientation correction and gravity alignment
"""

from .gravity_alignment import (
    estimate_gravity,
    compute_rotation_matrix,
    transform_to_world
)
from .heading import (
    compute_gps_heading,
    compute_perpendicular_accel
)

__all__ = [
    "estimate_gravity",
    "compute_rotation_matrix",
    "transform_to_world",
    "compute_gps_heading",
    "compute_perpendicular_accel"
]
