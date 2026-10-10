"""
atorvastatin_data.py
====================
The atorvastatin calcium production sheet, typed in as Python objects.

Each ProcessStage below = one group of rows in the sheet (row numbers are in
the `label`). The `reference={...}` dictionaries hold the numbers PRINTED in
the sheet, so the program can check its own calculation against them.

Some quantities in the sheet are not stated directly and were derived:
  * Stage 3 "Reaction mass (balance)": the sheet gives the stage total
    (1764.61 kg, Cp mix 0.7938) but only lists methanol + water, so the rest is
    entered as one balancing line whose Cp is chosen to reproduce Cp mix 0.7938.
  * Stage 15 (row 41) has no temperatures in the sheet. Heating 30 -> 75 degC is
    inferred because 230 kg x 1.2207 x 45 + 20 kg x 540 = 23434 kcal (the sheet value).
"""

from process_models import ProcessBatch, ProcessStage, StageMaterial, UtilityRates

M = StageMaterial   # short alias so the data below stays readable

# Totals printed at the bottom of the sheet (for 210 kg of product)
SHEET_TOTALS = {
    "heat_load": 660657,      # kcal (net: heating minus cooling)
    "steam_kg": 1554,         # kg  (reactor stages only)
    "chw_tr": 256, "chw_kw": 882,
    "brine_tr": 25, "brine_kw": 88,
    "power_kw": 152,
}


def build_atorvastatin_batch(name: str = "ATV-SHEET-001") -> ProcessBatch:
    """Return the batch described by the sheet: 225 kg ATI -> 210 kg atorvastatin calcium."""
    stages = [
        # ---------------- Equipment B1GLR008 ----------------
        ProcessStage(
            label="1-5", equipment="B1GLR008", operation="Heating",
            materials=[M("Methanol", 1768.5, 0.605, 2250),
                       M("ATI", 225.0, 0.30, 180),
                       M("Water", 113.0, 1.0, 113),
                       M("Conc. HCl", 3.55, 0.73, 3.0085)],
            time_hr=1, t_init=25, t_final=50, power_kw=7,
            reference={"heat_load": 31326, "steam_kg": 58, "chw_tr": 0, "brine_tr": 0, "cost": 60}),

        ProcessStage(
            label="6-8", equipment="B1GLR008", operation="Distillation",
            materials=[M("Reaction mass", 2110.05, 0.5938, 2546, is_fresh_charge=False)],
            time_hr=4, power_kw=7, latent_heat=263, removed_kg=884.25, removed_name="Methanol",
            reference={"heat_load": 232558, "steam_kg": 431, "chw_tr": 69, "brine_tr": 8, "cost": 224}),

        ProcessStage(
            label="9-11", equipment="B1GLR008", operation="Cooling",
            materials=[M("Methanol", 470.814, 0.605, 599, is_fresh_charge=False),
                       M("Water", 68.0, 1.0, 68, is_fresh_charge=False),
                       M("Reaction mass (balance)", 1225.796, 0.8549, is_fresh_charge=False)],
            time_hr=1.5, t_init=50, t_final=20, power_kw=7,
            reference={"heat_load": -42022, "steam_kg": 0, "chw_tr": 14, "brine_tr": 0, "cost": 668}),

        # ---------------- Equipment B1SSR003 ----------------
        ProcessStage(
            label="12-14", equipment="B1SSR003", operation="Cooling",
            materials=[M("Water", 1125.0, 1.0, 1125),
                       M("NaOH", 45.0, 0.63, 32.143)],
            time_hr=1.5, t_init=25, t_final=10, power_kw=7,
            reference={"heat_load": -17300, "steam_kg": 0, "chw_tr": 0, "brine_tr": 6, "cost": 330}),

        ProcessStage(
            label="15-17", equipment="B1SSR003", operation="Heating",
            materials=[M("NaOH solution", 1170.0, 0.9858, 1157.1, is_fresh_charge=False),
                       M("Reaction mass", 1764.61, 0.7938, 2088, is_fresh_charge=False)],
            time_hr=1, t_init=10, t_final=50, power_kw=7,
            reference={"heat_load": 102164, "steam_kg": 189, "chw_tr": 0, "brine_tr": 0, "cost": 56}),

        # ---------------- Equipment B1SSR006 ----------------
        ProcessStage(
            label="18-20", equipment="B1SSR006", operation="Distillation",
            materials=[M("Reaction mass", 2934.614, 0.8703, 3245.1, is_fresh_charge=False)],
            time_hr=4, power_kw=9, latent_heat=263, removed_kg=1355.064, removed_name="Methanol",
            reference={"heat_load": 356382, "steam_kg": 660, "chw_tr": 106, "brine_tr": 12, "cost": 13498}),

        ProcessStage(
            label="21-24", equipment="B1SSR006", operation="Charging",
            materials=[M("Water", 1125.0, 1.0, 1125),
                       M("Reaction mass", 1579.55, 0.870, 1521.1, is_fresh_charge=False),
                       M("MTBE", 1193.0, 1.605)],
            reference={"cost": 0}),

        # ---------------- Equipment B1SSR021 ----------------
        ProcessStage(
            label="25-28", equipment="B1SSR021", operation="Heating",
            materials=[M("Water", 23.0, 1.0, 23),
                       M("Reaction mass", 3897.55, 1.1326, 2916.1, is_fresh_charge=False),
                       M("MTBE", 906.66, 1.605, 270)],
            time_hr=1, t_init=40, t_final=48, power_kw=11.19,
            reference={"heat_load": 47142, "steam_kg": 87, "cost": 89.52}),

        ProcessStage(
            label="29-33", equipment="B1SSR021", operation="Heating",
            materials=[M("Atorvastatin Calcium (seed)", 11.2, 1.0, 9.3333),
                       M("Reaction mass", 4827.21, 1.2207, 3209.1, is_fresh_charge=False),
                       M("Water", 990.0, 1.0, 990),
                       M("Calcium Acetate", 40.5, 1.605, 270)],
            time_hr=1, t_init=50, t_final=60, power_kw=11.19,
            reference={"heat_load": 69589, "steam_kg": 129, "cost": 89.52}),

        ProcessStage(
            label="34", equipment="B1SSR021", operation="Cooling",
            materials=[M("Reaction mass", 4827.21, 1.2207, 3209.1, is_fresh_charge=False)],
            time_hr=1.5, t_init=60, t_final=30, power_kw=11.19,
            reference={"heat_load": -176781, "chw_tr": 58, "cost": 134.28}),

        # ---------------- Centrifuge ----------------
        ProcessStage(
            label="35-37", equipment="B1CNF001", operation="Centrifugation",
            materials=[M("Water", 1260.0, 1.0, 1260),
                       M("Reaction mass", 3917.48, 1.2207, 3209.1, is_fresh_charge=False)],
            time_hr=0.5, power_kw=11.4,
            notes="Output of this stage: 310 kg wet cake.",
            reference={"cost": 45.6}),

        # ---------------- Tray dryer B1ATD011 ----------------
        ProcessStage(
            label="38", equipment="B1ATD011", operation="Heating",
            materials=[M("Wet cake", 310.0, 1.2207, is_fresh_charge=False)],
            time_hr=1, t_init=35, t_final=75, power_kw=10,
            reference={"heat_load": 15137, "steam_kg": 28, "cost": 80}),

        ProcessStage(
            label="39", equipment="B1ATD011", operation="Drying",
            materials=[M("Wet cake", 310.0, 1.2207, is_fresh_charge=False)],
            time_hr=16, power_kw=10, latent_heat=540, removed_kg=80.0, removed_name="Moisture/solvent",
            notes="310 kg wet cake -> 230 kg semi-dry cake.",
            reference={"heat_load": 43200, "cost": 1280}),

        ProcessStage(
            label="40", equipment="B1ATD011", operation="Cooling",
            materials=[M("Semi-dry cake", 230.0, 1.2207, is_fresh_charge=False)],
            time_hr=1.5, t_init=75, t_final=30, power_kw=10,
            reference={"heat_load": -12634, "chw_tr": 4.178072, "cost": 120}),

        # ---------------- Rotary vacuum dryer B1RVD001 ----------------
        ProcessStage(
            label="41", equipment="B1RVD001", operation="Drying",
            materials=[M("Semi-dry cake", 230.0, 1.2207, is_fresh_charge=False)],
            time_hr=24, t_init=30, t_final=75, power_kw=15, latent_heat=540,
            removed_kg=20.0, removed_name="Moisture/solvent",
            notes="230 kg semi-dry cake -> 210 kg dry cake. Temperatures inferred (see file header).",
            reference={"heat_load": 23434, "steam_kg": 43, "cost": 2880}),

        ProcessStage(
            label="42", equipment="B1RVD001", operation="Cooling",
            materials=[M("Dry cake", 210.0, 1.2207, is_fresh_charge=False)],
            time_hr=1.5, t_init=75, t_final=30, power_kw=15,
            reference={"heat_load": -11536, "chw_tr": 3.814761, "cost": 180}),

        # ---------------- Pulveriser ----------------
        ProcessStage(
            label="43", equipment="B1PLV001", operation="Pulverizing",
            materials=[M("Dry cake", 210.0, is_fresh_charge=False)],
            time_hr=0.25, power_kw=2,
            reference={"cost": 4}),
    ]

    return ProcessBatch(
        name=name,
        product_name="Atorvastatin Calcium",
        key_input_name="ATI",
        key_input_kg=225.0,
        output_kg=210.0,
        stages=stages,
        rates=UtilityRates(),
        prices={},                       # raw-material prices are not in the sheet - add them via the menu
        reference_totals=dict(SHEET_TOTALS),
    )
