"""
calculator.py
=============
All the chemistry / cost maths lives here.

Main idea (step by step):
  1. Work out how much product we would get at 100 % yield ("theoretical").
        theoretical = target / (expected yield / 100)
  2. Convert that to moles of product.
  3. Use the balanced equation (stoichiometric coefficients) to find the
     moles - and then kg - of every reactant needed.
  4. Correct for excess charged and for purity of the material.
  5. Multiply kg by price -> raw material cost. Add solvent, labour,
     utilities and overhead -> total batch cost.
  6. Build a mass balance table (what went IN vs what came OUT).

numpy is used so all reactants are calculated together (vectorised),
pandas is used to build neat tables.
"""

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from models import Batch

# Change this one line to change the currency symbol used in reports.
CURRENCY = "$"


# --------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------
@dataclass
class BatchResult:
    """Everything the calculator produces for one batch."""
    batch: Batch
    theoretical_yield_kg: float        # product at 100 % yield
    output_kg: float                   # actual output if known, else target
    actual_yield_pct: float            # None-like (nan) if batch not yet run
    materials_df: pd.DataFrame         # each material: kind, kg, cost
    cost_breakdown: Dict[str, float]   # raw, solvent, labour, utility, overhead
    total_cost: float
    cost_per_kg: float
    mass_balance_df: pd.DataFrame      # IN / OUT streams
    closure_pct: float                 # (mass out / mass in) * 100
    atom_economy_pct: float
    e_factor: float
    revenue: float
    profit: float
    warnings: List[str]

    # -- pretty text report --------------------------------------------------
    def summary(self) -> str:
        """Return a human-readable report as a string."""
        b = self.batch
        lines = []
        lines.append("=" * 66)
        lines.append(f" BATCH REPORT : {b.name}   ({b.batch_date})")
        lines.append(f" Reaction     : {b.reaction.name}")
        lines.append("=" * 66)
        lines.append(f" Target output          : {b.target_output_kg:10.2f} kg")
        lines.append(f" Expected yield         : {b.expected_yield_pct:10.2f} %")
        lines.append(f" Theoretical yield      : {self.theoretical_yield_kg:10.2f} kg")
        if not np.isnan(self.actual_yield_pct):
            lines.append(f" Actual output          : {b.actual_output_kg:10.2f} kg")
            lines.append(f" Actual yield           : {self.actual_yield_pct:10.2f} %")
        else:
            lines.append(" Actual output          :   (batch not run yet - using target)")
        lines.append("")
        lines.append(" --- Raw materials & solvents to charge ---")
        lines.append(self.materials_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        lines.append("")
        lines.append(" --- Cost breakdown ---")
        for k, v in self.cost_breakdown.items():
            lines.append(f" {k:<22} {CURRENCY}{v:12,.2f}")
        lines.append(f" {'TOTAL BATCH COST':<22} {CURRENCY}{self.total_cost:12,.2f}")
        lines.append(f" {'COST PER kg PRODUCT':<22} {CURRENCY}{self.cost_per_kg:12,.2f}")
        if b.reaction.product.selling_price_per_kg > 0:
            lines.append(f" {'Revenue':<22} {CURRENCY}{self.revenue:12,.2f}")
            lines.append(f" {'Profit':<22} {CURRENCY}{self.profit:12,.2f}")
        lines.append("")
        lines.append(" --- Mass balance ---")
        lines.append(self.mass_balance_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        lines.append(f" Closure (out/in)       : {self.closure_pct:10.2f} %")
        lines.append("")
        lines.append(" --- Green-chemistry metrics ---")
        lines.append(f" Atom economy           : {self.atom_economy_pct:10.2f} %")
        lines.append(f" E-factor (kg waste/kg) : {self.e_factor:10.2f}")
        if self.warnings:
            lines.append("")
            lines.append(" --- Warnings ---")
            for w in self.warnings:
                lines.append(f" ! {w}")
        lines.append("=" * 66)
        return "\n".join(lines)


# --------------------------------------------------------------------------
# The calculator
# --------------------------------------------------------------------------
class BatchCalculator:
    """Takes a Batch object and returns a BatchResult."""

    def __init__(self, batch: Batch):
        self.batch = batch

    # -- helper: check that the chemical equation is balanced ---------------
    def _check_equation_balance(self) -> List[str]:
        """Total mass of reactants should equal total mass of products."""
        rx = self.batch.reaction
        mass_in = sum(r.coeff * r.molar_mass for r in rx.reactants)
        mass_out = rx.product.coeff * rx.product.molar_mass + sum(
            bp.coeff * bp.molar_mass for bp in rx.byproducts
        )
        # Allow 1 % difference for rounding of molar masses.
        if abs(mass_in - mass_out) / mass_in > 0.01:
            return [
                f"Equation looks unbalanced: reactants = {mass_in:.2f} g/mol, "
                f"products = {mass_out:.2f} g/mol. Check coefficients / by-products."
            ]
        return []

    # -- main entry point ---------------------------------------------------
    def calculate(self) -> BatchResult:
        b = self.batch
        rx = b.reaction
        prod = rx.product
        warnings = self._check_equation_balance()

        # STEP 1: theoretical yield (kg of product if reaction were 100 % efficient)
        theoretical_kg = b.target_output_kg / (b.expected_yield_pct / 100.0)

        # STEP 2: moles of product at 100 % yield  (kg -> g -> mol)
        moles_product = theoretical_kg * 1000.0 / prod.molar_mass

        # STEP 3: arrays with one entry per reactant (numpy = fast, tidy maths)
        names = [r.name for r in rx.reactants]
        coeffs = np.array([r.coeff for r in rx.reactants])
        mws = np.array([r.molar_mass for r in rx.reactants])
        purity = np.array([r.purity for r in rx.reactants])
        excess = np.array([r.excess_pct for r in rx.reactants])
        prices = np.array([r.cost_per_kg for r in rx.reactants])

        # moles of each reactant needed = moles product * (its coeff / product coeff)
        moles_needed = moles_product * coeffs / prod.coeff
        # exact (pure) kg needed
        pure_kg = moles_needed * mws / 1000.0
        # add the excess we deliberately charge
        charged_pure_kg = pure_kg * (1 + excess / 100.0)
        # material is not 100 % pure, so we must weigh out more
        charged_kg = charged_pure_kg / purity
        reactant_costs = charged_kg * prices

        # STEP 4: solvents (only the part that is NOT recovered is a real cost)
        solvent_rows = []
        solvent_cost = 0.0
        for s in b.solvents:
            net_used = s.mass_kg * (1 - s.recovery_pct / 100.0)
            cost = net_used * s.cost_per_kg
            solvent_cost += cost
            solvent_rows.append({"Material": s.name, "Kind": "Solvent",
                                 "Mass_kg": s.mass_kg, "Cost": cost})

        # Table of everything we need to charge
        rows = [
            {"Material": n, "Kind": "Reactant", "Mass_kg": m, "Cost": c}
            for n, m, c in zip(names, charged_kg, reactant_costs)
        ]
        materials_df = pd.DataFrame(rows + solvent_rows)

        # STEP 5: cost roll-up
        raw_cost = float(reactant_costs.sum())
        direct_cost = raw_cost + solvent_cost + b.labor_cost + b.utility_cost
        overhead_cost = direct_cost * b.overhead_pct / 100.0
        total_cost = direct_cost + overhead_cost

        cost_breakdown = {
            "Raw materials": raw_cost,
            "Solvents (net)": solvent_cost,
            "Labour": b.labor_cost,
            "Utilities": b.utility_cost,
            "Overhead": overhead_cost,
        }

        # STEP 6: actual yield and cost per kg
        if b.actual_output_kg is not None:
            if b.actual_output_kg > theoretical_kg * 1.0001:
                raise ValueError(
                    f"Actual output ({b.actual_output_kg} kg) is higher than the theoretical "
                    f"yield ({theoretical_kg:.2f} kg). That is physically impossible - check inputs."
                )
            output_kg = b.actual_output_kg
            actual_yield_pct = output_kg / theoretical_kg * 100.0
        else:
            output_kg = b.target_output_kg
            actual_yield_pct = float("nan")

        cost_per_kg = total_cost / output_kg
        revenue = output_kg * prod.selling_price_per_kg
        profit = revenue - total_cost

        # STEP 7: mass balance
        mass_balance_df, closure = self._mass_balance(
            names, coeffs, mws, charged_kg, charged_pure_kg, output_kg
        )

        # STEP 8: green-chemistry metrics
        # Atom economy = mass of desired product / mass of all reactants (from the equation)
        atom_economy = (prod.coeff * prod.molar_mass) / float((coeffs * mws).sum()) * 100.0
        total_in = float(mass_balance_df.loc[mass_balance_df["Direction"] == "IN", "Mass_kg"].sum())
        # E-factor = kg of waste per kg of product
        e_factor = (total_in - output_kg) / output_kg

        if closure < 99 or closure > 101:
            warnings.append(f"Mass balance closure is {closure:.2f} % (expected ~100 %).")

        return BatchResult(
            batch=b, theoretical_yield_kg=theoretical_kg, output_kg=output_kg,
            actual_yield_pct=actual_yield_pct, materials_df=materials_df,
            cost_breakdown=cost_breakdown, total_cost=total_cost, cost_per_kg=cost_per_kg,
            mass_balance_df=mass_balance_df, closure_pct=closure,
            atom_economy_pct=atom_economy, e_factor=e_factor,
            revenue=revenue, profit=profit, warnings=warnings,
        )

    # -- mass balance -------------------------------------------------------
    def _mass_balance(self, names, coeffs, mws, charged_kg, charged_pure_kg, output_kg):
        """
        Law of conservation of mass:  total IN = total OUT.

        IN  : every reactant (as weighed, including impurities) + all solvent
        OUT : product, by-products, unreacted reactant, impurities carried in
              with the raw materials, recovered solvent, lost solvent
        """
        b = self.batch
        prod = b.reaction.product
        streams = []   # list of (stream name, direction, kg)

        # ---- IN ----
        for n, kg in zip(names, charged_kg):
            streams.append((f"{n} (charged)", "IN", float(kg)))
        for s in b.solvents:
            streams.append((f"{s.name} (solvent)", "IN", s.mass_kg))

        # ---- OUT ----
        # Product actually made
        streams.append((f"{prod.name} (product)", "OUT", output_kg))

        # Moles of product really formed -> tells us how much reactant was consumed
        moles_product_actual = output_kg * 1000.0 / prod.molar_mass
        consumed_pure_kg = moles_product_actual * coeffs / prod.coeff * mws / 1000.0

        # By-products form in the same ratio as the product
        for bp in b.reaction.byproducts:
            bp_kg = moles_product_actual * bp.coeff / prod.coeff * bp.molar_mass / 1000.0
            streams.append((f"{bp.name} (by-product)", "OUT", float(bp_kg)))

        # Unreacted reactant = what we charged (pure) - what was consumed
        for n, charged, used in zip(names, charged_pure_kg, consumed_pure_kg):
            streams.append((f"{n} (unreacted)", "OUT", float(max(charged - used, 0.0))))

        # Impurities that came in with the raw materials
        for n, total, pure in zip(names, charged_kg, charged_pure_kg):
            imp = float(total - pure)
            if imp > 1e-9:
                streams.append((f"{n} impurities", "OUT", imp))

        # Solvent split into recovered vs lost
        for s in b.solvents:
            recovered = s.mass_kg * s.recovery_pct / 100.0
            streams.append((f"{s.name} recovered", "OUT", recovered))
            streams.append((f"{s.name} lost/waste", "OUT", s.mass_kg - recovered))

        df = pd.DataFrame(streams, columns=["Stream", "Direction", "Mass_kg"])
        total_in = df.loc[df["Direction"] == "IN", "Mass_kg"].sum()
        total_out = df.loc[df["Direction"] == "OUT", "Mass_kg"].sum()
        closure = float(total_out / total_in * 100.0)
        return df, closure
