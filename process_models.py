"""
process_models.py
=================
Data classes for a MULTI-STAGE production process (like the atorvastatin
calcium sheet: heating -> distillation -> cooling -> centrifuge -> drying ...).

    StageMaterial -> one line of the sheet (e.g. "Methanol 1768.5 kg, Cp 0.605")
    ProcessStage  -> one unit operation in one piece of equipment
    UtilityRates  -> steam / electricity / refrigeration constants and prices
    ProcessBatch  -> the whole process = list of stages + rates + prices

No calculations happen here (that is process_calculator.py) - only storage,
validation and a helper to scale the batch up or down.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Dict, List, Optional

# The kinds of unit operation the calculator understands.
OPERATIONS = ("Heating", "Cooling", "Distillation", "Drying",
              "Centrifugation", "Pulverizing", "Charging")


# --------------------------------------------------------------------------
# Utility constants and prices
# --------------------------------------------------------------------------
@dataclass
class UtilityRates:
    """
    Constants taken from / back-calculated from the production sheet.
    Change any of them to run a "what-if".
    """
    electricity_inr_per_kwh: float = 8.0    # sheet: kW x hr x 8  = cost in INR
    coal_inr_per_kg: float = 8.8            # sheet: "cost of coal per kg is 8.8 Rs"
    steam_kg_per_kg_coal: float = 5.0       # ASSUMED: 1 kg coal -> 5 kg steam (gives the sheet's 13.0 INR per kg product)
    steam_latent_heat: float = 540.0        # kcal per kg steam (the "540" in the sheet)
    kcal_per_tr_hr: float = 3024.0          # 1 ton of refrigeration = 3024 kcal/hr
    kw_per_tr: float = 3.5                  # compressor kW per TR (sheet: 14 TR -> 49 kW)
    refrigeration_safety_factor: float = 1.5  # applied to COOLING loads (sheet: 9.26 TR -> 14 TR)
    condenser_basis_hr: float = 1.0         # sheet sizes distillation condensers on total heat / 1 hr
    condenser_chw_share: float = 0.90       # 90 % chilled water, 10 % brine (sheet: 69 TR CHW + 8 TR brine)
    brine_below_c: float = 15.0             # cooling to a temperature below this uses brine, else chilled water

    @property
    def steam_inr_per_kg(self) -> float:
        """Cost of 1 kg of steam = coal price / kg steam made per kg coal."""
        return self.coal_inr_per_kg / self.steam_kg_per_kg_coal


# --------------------------------------------------------------------------
# One line of material inside a stage
# --------------------------------------------------------------------------
@dataclass
class StageMaterial:
    name: str
    mass_kg: float                       # "Qty, Kg" column
    cp: float = 0.0                      # specific heat, kcal/kg.degC
    volume_l: Optional[float] = None     # "Qty, L" column (information only)
    # True  -> a fresh raw material charged into the batch (counted in raw-material list & cost)
    # False -> material that is just carried over from the previous stage (e.g. "Reaction mass")
    is_fresh_charge: bool = True

    def __post_init__(self):
        if self.mass_kg < 0:
            raise ValueError(f"{self.name}: mass cannot be negative")
        if self.cp < 0:
            raise ValueError(f"{self.name}: Cp cannot be negative")


# --------------------------------------------------------------------------
# One unit operation
# --------------------------------------------------------------------------
@dataclass
class ProcessStage:
    label: str                            # e.g. "1-5" (row numbers in the sheet)
    equipment: str                        # e.g. "B1GLR008"
    operation: str                        # one of OPERATIONS
    materials: List[StageMaterial]
    time_hr: float = 0.0
    t_init: Optional[float] = None        # degC
    t_final: Optional[float] = None       # degC
    power_kw: float = 0.0                 # agitator / motor power of the equipment
    latent_heat: float = 0.0              # kcal/kg of the liquid removed (distillation, drying)
    removed_kg: float = 0.0               # kg distilled off / evaporated
    removed_name: str = ""                # e.g. "Methanol"
    reference: Dict[str, float] = field(default_factory=dict)  # values printed in the sheet (for validation)
    notes: str = ""

    def __post_init__(self):
        if self.operation not in OPERATIONS:
            raise ValueError(f"Unknown operation '{self.operation}'. Use one of {OPERATIONS}")
        if self.time_hr < 0 or self.power_kw < 0 or self.removed_kg < 0:
            raise ValueError(f"Stage {self.label}: time, power and removed mass cannot be negative")

    # Total mass in the stage = sum of all material lines
    @property
    def total_mass_kg(self) -> float:
        return sum(m.mass_kg for m in self.materials)

    # Cp of the mixture = mass-weighted average of the individual Cp values
    @property
    def cp_mix(self) -> float:
        total = self.total_mass_kg
        if total <= 0:
            return 0.0
        return sum(m.mass_kg * m.cp for m in self.materials) / total

    # Reactor stages (GLR / SSR) - the sheet's steam total counts only these
    @property
    def is_reactor(self) -> bool:
        return self.equipment.upper().startswith(("B1GLR", "B1SSR"))


# --------------------------------------------------------------------------
# The whole process
# --------------------------------------------------------------------------
@dataclass
class ProcessBatch:
    name: str
    product_name: str
    key_input_name: str                   # the main starting material (used for yield)
    key_input_kg: float
    output_kg: float                      # finished product made in this batch
    stages: List[ProcessStage]
    rates: UtilityRates = field(default_factory=UtilityRates)
    prices: Dict[str, float] = field(default_factory=dict)      # raw material INR/kg  (name -> price)
    reference_totals: Dict[str, float] = field(default_factory=dict)  # totals printed in the sheet
    batch_date: str = field(default_factory=lambda: date.today().isoformat())

    def __post_init__(self):
        if self.output_kg <= 0 or self.key_input_kg <= 0:
            raise ValueError("Output and key input must be > 0 kg")
        if not self.stages:
            raise ValueError("A process needs at least one stage")

    def scaled(self, new_output_kg: float) -> "ProcessBatch":
        """
        Scale every mass in the process so the batch makes `new_output_kg`.
        Heat loads scale with mass. Times, temperatures and equipment power
        are kept the same (i.e. same equipment and same cycle times).
        """
        f = new_output_kg / self.output_kg
        new_stages = []
        for st in self.stages:
            new_mats = [replace(m, mass_kg=m.mass_kg * f,
                                volume_l=None if m.volume_l is None else m.volume_l * f)
                        for m in st.materials]
            # sheet reference values no longer apply after scaling, so clear them
            new_stages.append(replace(st, materials=new_mats, removed_kg=st.removed_kg * f, reference={}))
        return replace(self, output_kg=new_output_kg, key_input_kg=self.key_input_kg * f,
                       stages=new_stages, reference_totals={})
