"""
Vehicle passport -> parameters of the guidebook equations Eq.4/5/6.

The recorder writes the carrier passport into the CSV comment layer (contract
v3: `# vehicle_*` lines, machine tokens shared with io/metadata.py). This module
turns that passport into the arguments of compute_iri_multi(): the equation set
(vehicle class) and the four vehicle factors (npeop, stif, dampf, tyres).

The guidebook defines the factors only as ranges (npeop 1..4 at 70 kg/person;
stif and dampf +-20 % around nominal; tyre size factor 0.7-1.0) and gives no
table that maps a real vehicle onto them, so every mapping below is a documented
assumption of the method (dissertation section 2) and is reported as such in the
provenance dict. DO NOT RETUNE the tables to a dataset: they are pinned in
tests/test_vehicle_params.py.

A missing or unknown token never fails the analysis: the parameter falls back to
the book default and the fallback is recorded as a warning.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .iri import IRI_MULTI_DEFAULT_PARAMS, VehicleType

# Guidebook vehicle classes reachable from the recorder body-type token. Every
# other body type (hatchback, crossover, suv, truck) has no class of its own in
# the guidebook and stays on the generic Eq.6.
EQUATION_BY_VEHICLE_TYPE = {
    'van': VehicleType.LEV,      # Eq.4, Large European Van
    'sedan': VehicleType.DSD,    # Eq.5, D-class sedan
}

EQUATION_TOKEN = {
    VehicleType.LEV: 'eq4',
    VehicleType.DSD: 'eq5',
    VehicleType.GENERIC: 'eq6',
}

# npeop: the guidebook variable is a passenger count (1..4, 70 kg each). Cargo
# load is mapped through the same mass equivalence - an assumption.
NPEOP_BY_LOAD = {
    'driver_only': 1.0,
    'two_people': 2.0,
    'half_load': 3.0,
    'full_load': 4.0,
}
_NPEOP_BOOK_TOKENS = {'driver_only', 'two_people'}   # literal passenger counts

# stif: +-20 % around nominal by suspension design (leaf spring stiffer, air softer)
STIF_BY_SUSPENSION_TYPE = {
    'leaf_spring': 1.2,
    'independent': 1.0,
    'torsion_beam': 1.0,
    'air': 0.8,
}

# dampf: a worn damper loses damping force; new and good are taken as nominal
DAMPF_BY_SUSPENSION_CONDITION = {
    'new': 1.0,
    'good': 1.0,
    'worn': 0.8,
}

# tyres: the guidebook gives a "tyre size factor" of 0.7-1.0 without a reference
# size. Rim diameter is the only size component a passport reliably carries, so
# the factor is stepped on it: 16" and larger nominal, 15" one step down, 14" and
# smaller at the lower bound. The weakest assumption of the table.
TYRES_NOMINAL_RIM_INCH = 16
TYRES_BY_RIM_STEP = {'nominal': 1.0, 'one_down': 0.9, 'small': 0.7}

_TYRE_SIZE_RE = re.compile(r'(\d{3})\s*/\s*(\d{2,3})\s*[rR]\s*(\d{2})')


@dataclass(frozen=True)
class ResolvedVehicleParams:
    vehicle_type: VehicleType
    equation: str                       # 'eq4' | 'eq5' | 'eq6'
    params: Dict[str, float]            # npeop, stif, dampf, tyres
    provenance: Dict[str, str]          # per key: 'book' | 'assumption' | 'default'
    mount_rigid: Optional[bool]
    warnings: List[str] = field(default_factory=list)


def tyre_size_factor(size: str) -> Optional[float]:
    """Tyre size factor from a '215/75R16' passport string; None when unparsable."""
    match = _TYRE_SIZE_RE.search(size or '')
    if match is None:
        return None
    rim_inch = int(match.group(3))
    if rim_inch >= TYRES_NOMINAL_RIM_INCH:
        return TYRES_BY_RIM_STEP['nominal']
    if rim_inch == TYRES_NOMINAL_RIM_INCH - 1:
        return TYRES_BY_RIM_STEP['one_down']
    return TYRES_BY_RIM_STEP['small']


def resolve_vehicle_params(vehicle: Dict[str, str]) -> ResolvedVehicleParams:
    """
    Map the `# vehicle_*` passport onto the Eq.4/5/6 arguments.

    An empty passport (pre-v3 recording) resolves to exactly what the pipeline
    used before the passport existed: GENERIC with IRI_MULTI_DEFAULT_PARAMS,
    every entry marked 'default'.
    """
    vehicle = vehicle or {}
    params = dict(IRI_MULTI_DEFAULT_PARAMS)
    provenance = {'equation': 'default', 'npeop': 'default', 'stif': 'default',
                  'dampf': 'default', 'tyres': 'default'}
    warnings: List[str] = []

    def pick(key: str, table: Dict[str, float], param: str, book_tokens=()):
        token = vehicle.get(key)
        if token is None:
            return
        if token not in table:
            warnings.append(
                f"{key}={token!r} is not a known token - {param} kept at book default")
            return
        params[param] = table[token]
        provenance[param] = 'book' if token in book_tokens else 'assumption'

    body = vehicle.get('vehicle_type')
    vehicle_type = EQUATION_BY_VEHICLE_TYPE.get(body, VehicleType.GENERIC)
    if body in EQUATION_BY_VEHICLE_TYPE:
        provenance['equation'] = 'book'

    pick('vehicle_load', NPEOP_BY_LOAD, 'npeop', book_tokens=_NPEOP_BOOK_TOKENS)
    pick('vehicle_suspension_type', STIF_BY_SUSPENSION_TYPE, 'stif')
    pick('vehicle_suspension_condition', DAMPF_BY_SUSPENSION_CONDITION, 'dampf')

    size = vehicle.get('vehicle_tire_size')
    if size is not None:
        factor = tyre_size_factor(size)
        if factor is None:
            warnings.append(
                f"vehicle_tire_size={size!r} is not parsable - tyres kept at book default")
        else:
            params['tyres'] = factor
            provenance['tyres'] = 'assumption'

    # The mount is not a term of Eq.4/5/6; a non-rigid mount lowers the
    # confidence in every Grms-based number and is reported, not modelled.
    mount_rigid = None
    rigid_token = vehicle.get('vehicle_mount_rigid')
    if rigid_token is not None:
        mount_rigid = rigid_token == 'true'
        if not mount_rigid:
            warnings.append(
                'vehicle_mount_rigid=false: non-rigid mount, lower confidence in '
                'Grms-based metrics')

    return ResolvedVehicleParams(
        vehicle_type=vehicle_type,
        equation=EQUATION_TOKEN[vehicle_type],
        params=params,
        provenance=provenance,
        mount_rigid=mount_rigid,
        warnings=warnings,
    )
