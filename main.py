"""
main.py
=======
Menu-driven program - run this file:   python main.py

It ties everything together:
    models.py      -> data classes
    calculator.py  -> maths
    database.py    -> SQL storage
    analysis.py    -> comparison + charts
"""

import sys
from dataclasses import replace
from typing import Optional

from analysis import (compare_batches, compare_process_batches, plot_batch_comparison, plot_cost_breakdown,
                      plot_mass_balance, plot_process_cost, plot_process_history, plot_stage_loads,
                      plot_utility_sensitivity, plot_yield_sensitivity)
from atorvastatin_data import build_atorvastatin_batch
from process_calculator import ProcessCalculator
from calculator import BatchCalculator, CURRENCY
from database import BatchDatabase
from models import Batch, ByProduct, Product, Reaction, Reactant, Solvent


# --------------------------------------------------------------------------
# Input helpers (keep asking until the user types something valid)
# --------------------------------------------------------------------------
def ask_text(prompt: str, default: Optional[str] = None) -> str:
    while True:
        text = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
        if text:
            return text
        if default is not None:
            return default


def ask_float(prompt: str, default: Optional[float] = None) -> float:
    while True:
        raw = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number.")


def ask_int(prompt: str, default: int = 0) -> int:
    return int(ask_float(prompt, default))


# --------------------------------------------------------------------------
# Demo data: paracetamol synthesis
#     4-aminophenol + acetic anhydride -> paracetamol + acetic acid
# --------------------------------------------------------------------------
def build_demo_batch(name: str, actual_kg: Optional[float] = None, date: str = None) -> Batch:
    reaction = Reaction(
        name="Paracetamol synthesis",
        reactants=[
            Reactant("4-Aminophenol", 109.13, 1, cost_per_kg=12.0, purity=0.99),
            Reactant("Acetic anhydride", 102.09, 1, cost_per_kg=3.0, purity=0.98, excess_pct=10),
        ],
        product=Product("Paracetamol", 151.16, 1, selling_price_per_kg=25.0),
        byproducts=[ByProduct("Acetic acid", 60.05, 1)],
    )
    batch = Batch(
        name=name, reaction=reaction,
        target_output_kg=100, expected_yield_pct=85,
        solvents=[Solvent("Ethanol", 50, 1.2, recovery_pct=80),
                  Solvent("Water", 200, 0.01, recovery_pct=0)],
        labor_cost=150, utility_cost=90, overhead_pct=15,
        actual_output_kg=actual_kg,
    )
    if date:
        batch.batch_date = date
    return batch


def load_demo_data(db: BatchDatabase):
    """Store a few example batches so comparison / charts have something to show."""
    demo = [("PCM-001", 99.0, "2026-01-10"), ("PCM-002", 96.5, "2026-02-14"),
            ("PCM-003", 92.0, "2026-03-20"), ("PCM-004", 101.5, "2026-04-25"),
            ("PCM-005", 103.0, "2026-05-30")]
    for name, actual, date in demo:
        result = BatchCalculator(build_demo_batch(name, actual, date)).calculate()
        db.save_result(result)
    print(f"Loaded {len(demo)} demo batches into the database.")


# --------------------------------------------------------------------------
# Interactive batch entry
# --------------------------------------------------------------------------
def input_batch() -> Batch:
    print("\n--- New batch ---")
    batch_name = ask_text("Batch name / number")
    rx_name = ask_text("Reaction name")

    # Product
    print("\nProduct:")
    p_name = ask_text("  Product name")
    p_mw = ask_float("  Molar mass (g/mol)")
    p_coeff = ask_float("  Stoichiometric coefficient", 1)
    p_price = ask_float("  Selling price per kg (0 if unknown)", 0)
    product = Product(p_name, p_mw, p_coeff, p_price)

    # Reactants
    reactants = []
    n = ask_int("\nNumber of reactants", 2)
    for i in range(1, n + 1):
        print(f"Reactant {i}:")
        reactants.append(Reactant(
            name=ask_text("  Name"),
            molar_mass=ask_float("  Molar mass (g/mol)"),
            coeff=ask_float("  Stoichiometric coefficient", 1),
            cost_per_kg=ask_float("  Cost per kg"),
            purity=ask_float("  Purity as fraction (0.98 = 98 %)", 1.0),
            excess_pct=ask_float("  Excess charged (%)", 0),
        ))

    # By-products
    byproducts = []
    n = ask_int("\nNumber of by-products", 0)
    for i in range(1, n + 1):
        print(f"By-product {i}:")
        byproducts.append(ByProduct(ask_text("  Name"), ask_float("  Molar mass (g/mol)"),
                                    ask_float("  Stoichiometric coefficient", 1)))

    # Solvents
    solvents = []
    n = ask_int("\nNumber of solvents", 0)
    for i in range(1, n + 1):
        print(f"Solvent {i}:")
        solvents.append(Solvent(ask_text("  Name"), ask_float("  Mass used (kg)"),
                                ask_float("  Cost per kg"), ask_float("  Recovery (%)", 0)))

    # Batch-level data
    print("\nBatch data:")
    target = ask_float("  Target output (kg)")
    exp_yield = ask_float("  Expected yield (%)", 85)
    labor = ask_float(f"  Labour cost ({CURRENCY})", 0)
    utility = ask_float(f"  Utility cost ({CURRENCY})", 0)
    overhead = ask_float("  Overhead (% of direct cost)", 0)
    actual_raw = ask_text("  Actual output in kg (press Enter if batch not run yet)", default="-")
    actual = None if actual_raw == "-" else float(actual_raw)

    return Batch(batch_name, Reaction(rx_name, reactants, product, byproducts),
                 target, exp_yield, solvents, labor, utility, overhead, actual)


# --------------------------------------------------------------------------
# Menu actions
# --------------------------------------------------------------------------
def action_new_batch(db: BatchDatabase):
    try:
        batch = input_batch()
        result = BatchCalculator(batch).calculate()
    except ValueError as err:                      # validation problems from models/calculator
        print(f"\nInput error: {err}")
        return
    print("\n" + result.summary())
    if ask_text("Save this batch to the database? (y/n)", "y").lower().startswith("y"):
        batch_id = db.save_result(result)
        print(f"Saved as batch_id {batch_id}.")
    if ask_text("Save charts (cost pie + mass balance)? (y/n)", "y").lower().startswith("y"):
        print("  ", plot_cost_breakdown(result))
        print("  ", plot_mass_balance(result))


def action_list(db: BatchDatabase):
    df = db.list_batches()
    if df.empty:
        print("\nDatabase is empty. Use option 1 (new batch) or option 7 (load demo data).")
    else:
        cols = ["batch_id", "batch_name", "batch_date", "product_name", "target_kg",
                "actual_output_kg", "actual_yield", "total_cost", "cost_per_kg"]
        print("\n" + df[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


def action_view(db: BatchDatabase):
    batch_id = ask_int("Batch ID to view")
    row = db.get_batch(batch_id)
    if row is None:
        print("No batch with that ID.")
        return
    print("\n" + row.to_string())
    print("\nMaterials:\n" + db.get_materials(batch_id).to_string(index=False,
          float_format=lambda x: f"{x:,.2f}"))


def action_update_actual(db: BatchDatabase):
    batch_id = ask_int("Batch ID")
    kg = ask_float("Actual output (kg)")
    try:
        print("Updated." if db.update_actual_output(batch_id, kg) else "No batch with that ID.")
    except ValueError as err:
        print(f"Error: {err}")


def action_compare(db: BatchDatabase):
    df = db.list_batches()
    print("\n" + compare_batches(df))
    if not df.dropna(subset=["actual_yield"]).empty:
        print("\nChart saved:", plot_batch_comparison(df))


def action_sensitivity():
    print("\nUsing the demo paracetamol batch for the yield what-if chart.")
    print("Chart saved:", plot_yield_sensitivity(build_demo_batch("PCM-DEMO")))


def action_delete(db: BatchDatabase):
    batch_id = ask_int("Batch ID to delete")
    print("Deleted." if db.delete_batch(batch_id) else "No batch with that ID.")


def action_demo_report():
    result = BatchCalculator(build_demo_batch("PCM-DEMO", actual_kg=99.0)).calculate()
    print("\n" + result.summary())
    print("Charts:", plot_cost_breakdown(result), plot_mass_balance(result))


# ==========================================================================
#  ATORVASTATIN PROCESS MENU (multi-stage production sheet)
# ==========================================================================
def load_sheet_batch(db: BatchDatabase, name: str = "ATV-SHEET-001"):
    """The sheet's batch, with the raw-material prices saved in the database."""
    return replace(build_atorvastatin_batch(name), prices=db.get_prices())


def p_report(db: BatchDatabase):
    result = ProcessCalculator(load_sheet_batch(db)).calculate()
    print("\n" + result.summary())


def p_validate(db: BatchDatabase):
    result = ProcessCalculator(load_sheet_batch(db)).calculate()
    print("\nCalculated values vs the numbers printed in the sheet:\n")
    print(result.validation_text())


def p_prices(db: BatchDatabase):
    """Enter / update raw-material prices (INR per kg) - saved in the database."""
    batch = load_sheet_batch(db)
    names = ProcessCalculator(batch)._raw_materials()[0]["Material"].tolist()
    print("\nRaw materials of the process (press Enter to keep the current price):")
    for name in names:
        current = db.get_prices().get(name)
        raw = input(f"  {name} - INR per kg [{'not set' if current is None else current}]: ").strip()
        if raw:
            try:
                db.set_price(name, float(raw))
            except ValueError as err:
                print(f"    Skipped: {err}")
    print("Prices saved.")


def p_run_custom(db: BatchDatabase):
    """Run the process for another batch size / tariff, then optionally save it."""
    name = ask_text("Batch name", "ATV-001")
    output = ask_float("Product to make (kg)", 210)
    base = load_sheet_batch(db, name)
    try:
        batch = base.scaled(output) if output != base.output_kg else base
        rates = replace(batch.rates,
                        electricity_inr_per_kwh=ask_float("Electricity tariff (INR/kWh)", batch.rates.electricity_inr_per_kwh),
                        coal_inr_per_kg=ask_float("Coal price (INR/kg)", batch.rates.coal_inr_per_kg))
        actual = ask_text("Actual product obtained in kg (Enter = same as planned)", default="-")
        batch = replace(batch, rates=rates,
                        output_kg=batch.output_kg if actual == "-" else float(actual))
        result = ProcessCalculator(batch).calculate()
    except ValueError as err:
        print(f"\nInput error: {err}")
        return
    print("\n" + result.summary())
    if ask_text("Save this batch to the database? (y/n)", "y").lower().startswith("y"):
        print(f"Saved as process batch id {db.save_process_result(result)}.")
    if ask_text("Save charts? (y/n)", "y").lower().startswith("y"):
        print("  ", plot_stage_loads(result))
        print("  ", plot_process_cost(result))


def p_list(db: BatchDatabase):
    df = db.list_process_batches()
    if df.empty:
        print("\nNo process batches stored. Use option 3 (run & save) or option 9 (simulated history).")
        return
    cols = ["pbatch_id", "batch_name", "batch_date", "output_kg", "yield_pct", "total_cost", "cost_per_kg"]
    print("\n" + df[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


def p_view(db: BatchDatabase):
    pid = ask_int("Process batch ID")
    stages = db.get_process_stages(pid)
    if stages.empty:
        print("No process batch with that ID.")
        return
    print("\n" + stages.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))


def p_compare(db: BatchDatabase):
    df = db.list_process_batches()
    print("\n" + compare_process_batches(df))
    if not df.empty:
        print("\nChart saved:", plot_process_history(df))
        hist = db.stage_cost_history("Distillation")      # SQL JOIN across both tables
        if not hist.empty:
            print("\nDistillation stage cost across batches (SQL JOIN):")
            print(hist.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))


def p_charts(db: BatchDatabase):
    batch = load_sheet_batch(db)
    result = ProcessCalculator(batch).calculate()
    print("\nCharts saved:")
    for path in (plot_stage_loads(result), plot_process_cost(result), plot_utility_sensitivity(batch)):
        print("  ", path)


def p_demo_history(db: BatchDatabase):
    """
    Store four SIMULATED repeat runs so history/comparison has data.
    Only the product recovered and the energy prices change - these are
    made-up example values, NOT real plant data.
    """
    runs = [("ATV-SIM-1", 205.0, 8.0, 8.8, "2026-06-01"), ("ATV-SIM-2", 210.0, 8.5, 9.2, "2026-07-01"),
            ("ATV-SIM-3", 197.0, 8.5, 9.0, "2026-08-01"), ("ATV-SIM-4", 212.0, 9.0, 9.5, "2026-09-01")]
    for name, out, tariff, coal, date in runs:
        b = load_sheet_batch(db, name)
        rates = replace(b.rates, electricity_inr_per_kwh=tariff, coal_inr_per_kg=coal)
        b = replace(b, output_kg=out, rates=rates, batch_date=date, reference_totals={})
        db.save_process_result(ProcessCalculator(b).calculate())
    print("Stored 4 SIMULATED batches (example data only).")


def p_delete(db: BatchDatabase):
    pid = ask_int("Process batch ID to delete")
    print("Deleted." if db.delete_process_batch(pid) else "No process batch with that ID.")


PROCESS_MENU = """
---- Atorvastatin Calcium process (from the production sheet) ----
 1. Full report for the sheet batch (210 kg)
 2. Validate calculation against the sheet
 3. Run for another batch size / tariff (and save)
 4. Enter raw-material prices
 5. List stored process batches
 6. View stages of a stored batch
 7. Compare stored batches (statistics + chart)
 8. Charts for the sheet batch (heat load, cost, sensitivity)
 9. Load simulated history (example data)
10. Delete a stored batch
 0. Back
"""


def process_menu(db: BatchDatabase):
    actions = {"1": p_report, "2": p_validate, "3": p_run_custom, "4": p_prices, "5": p_list,
               "6": p_view, "7": p_compare, "8": p_charts, "9": p_demo_history, "10": p_delete}
    while True:
        print(PROCESS_MENU)
        choice = input("Choose an option: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if action is None:
            print("Invalid choice.")
            continue
        try:
            action(db)
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")


# --------------------------------------------------------------------------
# Generic stoichiometric batch menu (original module, e.g. paracetamol demo)
# --------------------------------------------------------------------------
MENU = """
---- Generic stoichiometric batch calculator ----
 1. New batch (enter data, calculate, save)
 2. List all stored batches
 3. View one batch
 4. Record actual output of a batch
 5. Compare batches (statistics + chart)
 6. Yield sensitivity chart (demo batch)
 7. Load demo data into database
 8. Show demo batch report
 9. Delete a batch
 0. Back
"""


def stoich_menu(db: BatchDatabase):
    actions = {
        "1": lambda: action_new_batch(db), "2": lambda: action_list(db),
        "3": lambda: action_view(db), "4": lambda: action_update_actual(db),
        "5": lambda: action_compare(db), "6": action_sensitivity,
        "7": lambda: load_demo_data(db), "8": action_demo_report,
        "9": lambda: action_delete(db),
    }
    while True:
        print(MENU)
        choice = input("Choose an option: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if action is None:
            print("Invalid choice.")
            continue
        try:
            action()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")


# --------------------------------------------------------------------------
# Top-level menu
# --------------------------------------------------------------------------
TOP_MENU = """
==== Pharma Batch Cost & Mass Balance Calculator ====
 1. Atorvastatin Calcium process (multi-stage sheet)
 2. Generic stoichiometric batch calculator
 0. Exit
"""


def main():
    db = BatchDatabase()            # creates batch_records.db on first run
    while True:
        print(TOP_MENU)
        choice = input("Choose an option: ").strip()
        if choice == "1":
            process_menu(db)
        elif choice == "2":
            stoich_menu(db)
        elif choice == "0":
            print("Goodbye!")
            sys.exit(0)
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
