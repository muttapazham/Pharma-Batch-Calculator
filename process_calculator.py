"""
process_calculator.py
=====================
Calculates a multi-stage process (see process_models.py) the same way the
production sheet does:

  HEATING      Q = mass x Cp_mix x (T_final - T_init)                [kcal]
  COOLING      same formula, Q is negative
  DISTILLATION Q = kg distilled x latent heat (263 kcal/kg methanol)
  DRYING       Q = kg evaporated x 540  (+ sensible heat if temps are given)

  Steam (kg)          = Q / 540                       (only when Q > 0)
  Cooling refrigeration (TR) = |Q| / time / 3024 x 1.5 (safety factor)
  Condenser refrigeration    = Q / 3024   -> 90 % chilled water, 10 % brine
  Refrigeration power (kW)   = TR x 3.5

  Cost = equipment kW x hr x tariff
       + refrigeration kW x hr x tariff
       + steam kg x steam price
       + raw materials kg x price (only for materials with a known price)

Finally it builds a process mass balance, yield, E-factor and compares
everything with the numbers printed in the sheet.
"""

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from process_models import ProcessBatch, ProcessStage, UtilityRates

CURRENCY = "INR"


# --------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------
@dataclass
class ProcessResult:
    batch: ProcessBatch
    stages_df: pd.DataFrame          # one row per stage
    totals: Dict[str, float]         # sums over all stages
    per_kg: Dict[str, float]         # totals / kg of product
    cost_breakdown: Dict[str, float]
    total_cost: float
    cost_per_kg: float
    materials_df: pd.DataFrame       # fresh raw materials needed for the batch
    mass_balance_df: pd.DataFrame
    yield_pct: float                 # kg product / kg key input x 100
    e_factor: float
    validation_df: pd.DataFrame      # calculated vs sheet
    warnings: List[str]

    def summary(self) -> str:
        """Human-readable report."""
        b = self.batch
        t, pk = self.totals, self.per_kg
        f2 = lambda x: f"{x:,.2f}"
        L = []
        L.append("=" * 78)
        L.append(f" PROCESS REPORT : {b.name}   ({b.batch_date})")
        L.append(f" Product        : {b.product_name}   |   Output {b.output_kg:,.1f} kg")
        L.append("=" * 78)
        L.append(f" Key input ({b.key_input_name}) : {b.key_input_kg:,.1f} kg  ->  weight yield {self.yield_pct:.2f} %")
        L.append("")
        L.append(" --- Stage-by-stage utilities ---")
        show = self.stages_df[["Stage", "Equipment", "Operation", "Time_hr", "Heat_kcal", "Steam_kg",
                               "CHW_TR", "Brine_TR", "Power_kW", "Total_INR"]]
        L.append(show.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
        L.append("")
        L.append(" --- Totals for the batch  |  per kg of product ---")
        rows = [("Net heat load (kcal)", "heat_kcal"), ("Steam - all stages (kg)", "steam_kg"),
                ("Steam - reactors only (kg)", "steam_reactor_kg"), ("Chilled water (TR)", "chw_tr"),
                ("Chilled water (kW)", "chw_kw"), ("Brine (TR)", "brine_tr"), ("Brine (kW)", "brine_kw"),
                ("Equipment power (kW, sum)", "power_kw")]
        for label, key in rows:
            L.append(f" {label:<28}{t[key]:>14,.1f}   |  {pk[key]:>10,.2f}")
        L.append("")
        L.append(" --- Fresh raw materials to charge ---")
        L.append(self.materials_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        L.append("")
        L.append(f" --- Cost ({CURRENCY}) ---")
        for k, v in self.cost_breakdown.items():
            L.append(f" {k:<34}{v:>14,.2f}")
        L.append(f" {'TOTAL BATCH COST':<34}{self.total_cost:>14,.2f}")
        L.append(f" {'COST PER kg PRODUCT':<34}{self.cost_per_kg:>14,.2f}")
        L.append("")
        L.append(" --- Mass balance (fresh charges vs identified outputs) ---")
        L.append(self.mass_balance_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
        L.append(f" E-factor (kg waste / kg product) : {self.e_factor:.1f}")
        if self.warnings:
            L.append("")
            L.append(" --- Notes & warnings ---")
            for w in self.warnings:
                L.append(f" ! {w}")
        L.append("=" * 78)
        return "\n".join(L)

    def validation_text(self) -> str:
        """Report of calculated values against the numbers printed in the sheet."""
        if self.validation_df.empty:
            return "No sheet reference values attached to this batch (e.g. it was scaled)."
        v = self.validation_df
        bad = v[v["Status"] != "OK"]
        out = [v.to_string(index=False, float_format=lambda x: f"{x:,.2f}"), ""]
        out.append(f"{len(v) - len(bad)} of {len(v)} checks match the sheet within tolerance.")
        return "\n".join(out)


# --------------------------------------------------------------------------
# Calculator
# --------------------------------------------------------------------------
class ProcessCalculator:
    TOLERANCE_PCT = 2.0     # differences up to 2 % are treated as rounding

    def __init__(self, batch: ProcessBatch):
        self.batch = batch

    # -- one stage --------------------------------------------------------
    def _calc_stage(self, st: ProcessStage, r: UtilityRates) -> dict:
        op = st.operation
        mass, cp = st.total_mass_kg, st.cp_mix

        # temperature change (0 if the stage has no temperatures)
        dT = 0.0
        if st.t_init is not None and st.t_final is not None:
            dT = st.t_final - st.t_init
        sensible = mass * cp * dT                       # m . Cp . dT
        latent = st.removed_kg * st.latent_heat         # kg removed x latent heat

        # --- heat load Q (kcal) ---
        if op in ("Heating", "Cooling"):
            q = sensible
        elif op in ("Distillation", "Drying"):
            q = latent + sensible
        else:
            q = 0.0

        # --- steam ---
        steam = q / r.steam_latent_heat if (q > 0 and op in ("Heating", "Distillation", "Drying")) else 0.0

        # --- refrigeration (chilled water / brine) ---
        chw_tr = brine_tr = 0.0
        if op == "Cooling":
            if st.time_hr <= 0:
                raise ValueError(f"Stage {st.label}: a cooling stage needs time > 0")
            # average hourly load, plus the safety factor
            tr = abs(q) / st.time_hr / r.kcal_per_tr_hr * r.refrigeration_safety_factor
            if st.t_final is not None and st.t_final < r.brine_below_c:
                brine_tr = tr                            # very cold -> brine
            else:
                chw_tr = tr                              # else chilled water
        elif op == "Distillation":
            # condenser has to remove the heat that was put in
            tr = q / (r.condenser_basis_hr * r.kcal_per_tr_hr)
            chw_tr = tr * r.condenser_chw_share
            brine_tr = tr * (1 - r.condenser_chw_share)

        chw_kw, brine_kw = chw_tr * r.kw_per_tr, brine_tr * r.kw_per_tr

        # --- cost ---
        equip_cost = st.power_kw * st.time_hr * r.electricity_inr_per_kwh
        refrig_cost = (chw_kw + brine_kw) * st.time_hr * r.electricity_inr_per_kwh
        steam_cost = steam * r.steam_inr_per_kg

        return {
            "Stage": st.label, "Equipment": st.equipment, "Operation": op, "Time_hr": st.time_hr,
            "Mass_kg": mass, "Cp_mix": cp, "Heat_kcal": q, "Steam_kg": steam,
            "CHW_TR": chw_tr, "CHW_kW": chw_kw, "Brine_TR": brine_tr, "Brine_kW": brine_kw,
            "Power_kW": st.power_kw, "Equip_INR": equip_cost, "Refrig_INR": refrig_cost,
            "Steam_INR": steam_cost, "Total_INR": equip_cost + refrig_cost + steam_cost,
            "_reactor": st.is_reactor,
        }

    # -- whole process ----------------------------------------------------
    def calculate(self) -> ProcessResult:
        b, r = self.batch, self.batch.rates
        warnings: List[str] = []

        rows = [self._calc_stage(st, r) for st in b.stages]
        df = pd.DataFrame(rows)

        # totals over all stages (pandas does the summing)
        totals = {
            "heat_kcal": df["Heat_kcal"].sum(),
            "steam_kg": df["Steam_kg"].sum(),
            "steam_reactor_kg": df.loc[df["_reactor"], "Steam_kg"].sum(),
            "chw_tr": df["CHW_TR"].sum(), "chw_kw": df["CHW_kW"].sum(),
            "brine_tr": df["Brine_TR"].sum(), "brine_kw": df["Brine_kW"].sum(),
            "power_kw": df["Power_kW"].sum(),
        }
        per_kg = {k: v / b.output_kg for k, v in totals.items()}

        # fresh raw materials (aggregate the same material used in several stages)
        materials_df, raw_cost, unpriced = self._raw_materials()
        if unpriced:
            warnings.append("No price entered for: " + ", ".join(unpriced) +
                            " -> raw-material cost is incomplete (set prices in the menu).")

        cost_breakdown = {
            "Equipment electricity": float(df["Equip_INR"].sum()),
            "Refrigeration electricity": float(df["Refrig_INR"].sum()),
            f"Steam ({r.coal_inr_per_kg:.1f}/kg coal, {r.steam_kg_per_kg_coal:g} kg steam/kg coal)": float(df["Steam_INR"].sum()),
            "Raw materials (priced only)": raw_cost,
        }
        total_cost = sum(cost_breakdown.values())

        mass_df, e_factor, mb_warnings = self._mass_balance(materials_df)
        warnings += mb_warnings

        yield_pct = b.output_kg / b.key_input_kg * 100.0
        validation_df = self._validate(df, totals)

        # note about the sheet's steam total
        dryer_steam = totals["steam_kg"] - totals["steam_reactor_kg"]
        if dryer_steam > 0.5 and b.reference_totals:
            warnings.append(f"The sheet's steam total ({b.reference_totals.get('steam_kg', 0):,.0f} kg) counts reactors only; "
                            f"dryer stages need another {dryer_steam:,.0f} kg steam (all stages: {totals['steam_kg']:,.0f} kg).")

        # note about the sheet's electricity cost column
        sheet_cost = sum(st.reference.get("cost", 0.0) for st in b.stages)
        if sheet_cost > 0:
            full_elec = cost_breakdown["Equipment electricity"] + cost_breakdown["Refrigeration electricity"]
            if full_elec > sheet_cost * 1.05:
                warnings.append(f"The sheet's stage costs add up to {sheet_cost:,.0f} INR because chiller power is included "
                                f"in only 3 stages (9-11, 12-14, 18-20). Counting chiller power in every "
                                f"stage gives {full_elec:,.0f} INR of electricity.")

        return ProcessResult(
            batch=b, stages_df=df.drop(columns="_reactor"), totals=totals, per_kg=per_kg,
            cost_breakdown=cost_breakdown, total_cost=total_cost,
            cost_per_kg=total_cost / b.output_kg, materials_df=materials_df,
            mass_balance_df=mass_df, yield_pct=yield_pct, e_factor=e_factor,
            validation_df=validation_df, warnings=warnings)

    # -- raw material list ------------------------------------------------
    def _raw_materials(self):
        """Add up all FRESH charges by name and price them where a price is known."""
        totals: Dict[str, float] = {}
        for st in self.batch.stages:
            for m in st.materials:
                if m.is_fresh_charge:
                    totals[m.name] = totals.get(m.name, 0.0) + m.mass_kg
        rows, raw_cost, unpriced = [], 0.0, []
        for name, kg in totals.items():
            price = self.batch.prices.get(name)
            cost = kg * price if price is not None else np.nan
            if price is None:
                unpriced.append(name)
            else:
                raw_cost += cost
            rows.append({"Material": name, "Mass_kg": kg,
                         "Price_INR_per_kg": np.nan if price is None else price, "Cost_INR": cost})
        df = pd.DataFrame(rows).sort_values("Mass_kg", ascending=False).reset_index(drop=True)
        return df, raw_cost, unpriced

    # -- mass balance -----------------------------------------------------
    def _mass_balance(self, materials_df: pd.DataFrame):
        """
        IN  = fresh raw materials.
        OUT = product + solvent recovered by distillation + moisture evaporated in dryers
              + "effluent / mother liquor" (everything else - found BY DIFFERENCE).
        """
        b = self.batch
        warnings = []
        streams = [(f"{r.Material} (charged)", "IN", r.Mass_kg) for r in materials_df.itertuples()]
        total_in = float(materials_df["Mass_kg"].sum())

        recovered: Dict[str, float] = {}
        evaporated = 0.0
        for st in b.stages:
            if st.operation == "Distillation":
                recovered[st.removed_name] = recovered.get(st.removed_name, 0.0) + st.removed_kg
            elif st.operation == "Drying":
                evaporated += st.removed_kg

        out_rows = [(f"{b.product_name} (product)", "OUT", b.output_kg)]
        out_rows += [(f"{n} recovered (distillation)", "OUT", kg) for n, kg in recovered.items()]
        if evaporated > 0:
            out_rows.append(("Moisture/solvent evaporated (dryers)", "OUT", evaporated))
        identified = sum(x[2] for x in out_rows)
        effluent = total_in - identified
        if effluent < 0:
            warnings.append("Identified outputs are larger than the fresh charges - check the input data.")
        out_rows.append(("Effluent / mother liquor (by difference)", "OUT", max(effluent, 0.0)))
        streams += out_rows

        # sanity check: cannot recover more solvent than was charged
        charged = {r.Material.lower(): r.Mass_kg for r in materials_df.itertuples()}
        for name, kg in recovered.items():
            c = charged.get(name.lower())
            if c is not None and kg > c * 1.02:
                warnings.append(f"Sheet inconsistency: {kg:,.0f} kg {name} is recovered by distillation "
                                f"but only {c:,.0f} kg was charged.")

        e_factor = (total_in - b.output_kg) / b.output_kg
        return pd.DataFrame(streams, columns=["Stream", "Direction", "Mass_kg"]), e_factor, warnings

    # -- validation against the sheet ------------------------------------
    def _validate(self, df: pd.DataFrame, totals: Dict[str, float]) -> pd.DataFrame:
        """Compare stage-level and total values with the numbers printed in the sheet."""
        b = self.batch
        rows = []

        def add(where, metric, sheet, calc):
            diff = 0.0 if sheet == calc else (calc - sheet) / sheet * 100.0 if sheet else float("inf")
            ok = abs(diff) <= self.TOLERANCE_PCT or abs(calc - sheet) < 1.0   # tiny absolute gaps are rounding
            rows.append({"Where": where, "Metric": metric, "Sheet": sheet, "Calculated": calc,
                         "Diff_%": diff, "Status": "OK" if ok else "CHECK"})

        colmap = {"heat_load": "Heat_kcal", "steam_kg": "Steam_kg", "chw_tr": "CHW_TR", "brine_tr": "Brine_TR"}
        for st, row in zip(b.stages, df.itertuples()):
            for key, ref in st.reference.items():
                if key in colmap:
                    add(f"Stage {st.label}", key, ref, getattr(row, colmap[key]))
                elif key == "cost":
                    # sheet includes chiller electricity in only some stages -> use the closer match
                    eq, eq_ref = row.Equip_INR, row.Equip_INR + row.Refrig_INR
                    if abs(eq - ref) <= abs(eq_ref - ref):
                        add(f"Stage {st.label}", "cost (equipment kWh)", ref, eq)
                    else:
                        add(f"Stage {st.label}", "cost (equip + chiller kWh)", ref, eq_ref)

        tmap = {"heat_load": "heat_kcal", "steam_kg": "steam_reactor_kg", "chw_tr": "chw_tr",
                "chw_kw": "chw_kw", "brine_tr": "brine_tr", "brine_kw": "brine_kw", "power_kw": "power_kw"}
        for key, ref in b.reference_totals.items():
            if key in tmap:
                add("TOTAL", key, ref, totals[tmap[key]])
        return pd.DataFrame(rows)
