"""
models.py
=========
Plain data classes that describe a pharmaceutical batch.

Think of these as "forms" that hold the information the user gives us:
    Reactant  -> a starting material that is consumed in the reaction
    Product   -> the drug / intermediate we want to make
    ByProduct -> an unwanted (but expected) side product, e.g. acetic acid
    Solvent   -> a liquid that does NOT react (may be partly recovered)
    Reaction  -> groups reactants + product + by-products together
    Batch     -> a Reaction plus the size of the run and the extra costs

No calculations happen here - only storage and input validation.
The maths lives in calculator.py.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# --------------------------------------------------------------------------
# Small building blocks
# --------------------------------------------------------------------------
@dataclass
class Reactant:
    """A raw material that is consumed by the reaction."""
    name: str
    molar_mass: float            # g/mol  (e.g. 109.13 for 4-aminophenol)
    coeff: float                 # stoichiometric coefficient in the balanced equation
    cost_per_kg: float           # price of the material as purchased
    purity: float = 1.0          # fraction, 0.98 means 98 % pure
    excess_pct: float = 0.0      # % charged above the exact stoichiometric amount

    def __post_init__(self):
        # Validate inputs early so we get a clear error message,
        # instead of a confusing wrong answer later.
        if self.molar_mass <= 0:
            raise ValueError(f"{self.name}: molar mass must be > 0")
        if self.coeff <= 0:
            raise ValueError(f"{self.name}: stoichiometric coefficient must be > 0")
        if self.cost_per_kg < 0:
            raise ValueError(f"{self.name}: cost cannot be negative")
        if not (0 < self.purity <= 1):
            raise ValueError(f"{self.name}: purity must be between 0 and 1 (e.g. 0.98)")
        if self.excess_pct < 0:
            raise ValueError(f"{self.name}: excess % cannot be negative")


@dataclass
class Product:
    """The main product of the reaction."""
    name: str
    molar_mass: float                 # g/mol
    coeff: float = 1.0                # usually 1
    selling_price_per_kg: float = 0.0  # optional - only used for profit estimate

    def __post_init__(self):
        if self.molar_mass <= 0:
            raise ValueError(f"{self.name}: molar mass must be > 0")
        if self.coeff <= 0:
            raise ValueError(f"{self.name}: coefficient must be > 0")


@dataclass
class ByProduct:
    """A side product formed together with the main product (e.g. water, HCl)."""
    name: str
    molar_mass: float   # g/mol
    coeff: float        # coefficient in the balanced equation

    def __post_init__(self):
        if self.molar_mass <= 0 or self.coeff <= 0:
            raise ValueError(f"{self.name}: molar mass and coefficient must be > 0")


@dataclass
class Solvent:
    """A non-reacting liquid. A fraction can be recovered and reused."""
    name: str
    mass_kg: float
    cost_per_kg: float
    recovery_pct: float = 0.0   # % of solvent recovered by distillation

    def __post_init__(self):
        if self.mass_kg < 0 or self.cost_per_kg < 0:
            raise ValueError(f"{self.name}: mass and cost cannot be negative")
        if not (0 <= self.recovery_pct <= 100):
            raise ValueError(f"{self.name}: recovery % must be between 0 and 100")


# --------------------------------------------------------------------------
# Bigger building blocks
# --------------------------------------------------------------------------
@dataclass
class Reaction:
    """
    A balanced chemical reaction:
        a*Reactant1 + b*Reactant2 -> c*Product + d*ByProduct
    """
    name: str
    reactants: List[Reactant]
    product: Product
    byproducts: List[ByProduct] = field(default_factory=list)

    def __post_init__(self):
        if not self.reactants:
            raise ValueError("A reaction needs at least one reactant")


@dataclass
class Batch:
    """One production run: a reaction + the scale + the extra costs."""
    name: str                          # e.g. "PCM-2026-001"
    reaction: Reaction
    target_output_kg: float            # how much good product we WANT
    expected_yield_pct: float          # planned yield, e.g. 85
    solvents: List[Solvent] = field(default_factory=list)
    labor_cost: float = 0.0            # total labour cost for the batch
    utility_cost: float = 0.0          # steam, power, cooling water ...
    overhead_pct: float = 0.0          # % of direct cost added as overhead
    actual_output_kg: Optional[float] = None   # fill in AFTER the batch is done
    batch_date: str = field(default_factory=lambda: date.today().isoformat())

    def __post_init__(self):
        if self.target_output_kg <= 0:
            raise ValueError("Target output must be > 0 kg")
        if not (0 < self.expected_yield_pct <= 100):
            raise ValueError("Expected yield must be between 0 and 100 %")
        if min(self.labor_cost, self.utility_cost, self.overhead_pct) < 0:
            raise ValueError("Labour, utility and overhead cannot be negative")
        if self.actual_output_kg is not None and self.actual_output_kg <= 0:
            raise ValueError("Actual output must be > 0 kg (or leave it empty)")
