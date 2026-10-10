"""
analysis.py
===========
Compare batches from the database and draw charts.

Libraries used and why:
    pandas      -> tables of historical batches
    numpy       -> number ranges for the "what-if" yield curve
    scipy.stats -> linear trend of yield over time + outlier detection
    matplotlib  -> saves charts as PNG files
"""

import os
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")            # draw to files (works without a display / GUI)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from calculator import BatchCalculator, BatchResult, CURRENCY
from models import Batch
from process_calculator import ProcessCalculator, ProcessResult
from process_models import ProcessBatch

OUTPUT_DIR = "plots"


def _ensure_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


# --------------------------------------------------------------------------
# 1. Historical comparison (uses data loaded from the database)
# --------------------------------------------------------------------------
def compare_batches(df: pd.DataFrame) -> str:
    """Return a text table + statistics comparing all batches in df."""
    if df.empty:
        return "No batches stored yet."

    cols = ["batch_id", "batch_name", "product_name", "target_kg", "actual_output_kg",
            "actual_yield", "total_cost", "cost_per_kg", "e_factor"]
    out = [df[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"), ""]

    # Only batches that have really been run have an actual yield.
    done = df.dropna(subset=["actual_yield"])
    if len(done) >= 1:
        out.append(f"Average actual yield : {done['actual_yield'].mean():.2f} %")
        out.append(f"Best  batch          : {done.loc[done['actual_yield'].idxmax(), 'batch_name']}"
                   f" ({done['actual_yield'].max():.2f} %)")
        out.append(f"Worst batch          : {done.loc[done['actual_yield'].idxmin(), 'batch_name']}"
                   f" ({done['actual_yield'].min():.2f} %)")
        out.append(f"Average cost per kg  : {CURRENCY}{done['cost_per_kg'].mean():,.2f}")

    # scipy: is yield getting better or worse over time?
    if len(done) >= 3:
        x = np.arange(len(done))                       # 0,1,2,... = batch order
        fit = stats.linregress(x, done["actual_yield"])  # straight-line fit
        direction = "improving" if fit.slope > 0 else "declining"
        out.append(f"Yield trend          : {fit.slope:+.3f} % per batch ({direction}), "
                   f"R² = {fit.rvalue**2:.2f}, p = {fit.pvalue:.3f}")

        # z-score: how many standard deviations is each batch from the average?
        z = stats.zscore(done["actual_yield"], ddof=1)
        outliers = done.loc[np.abs(z) > 2, "batch_name"].tolist()
        out.append("Yield outliers (|z|>2): " + (", ".join(outliers) if outliers else "none"))
    else:
        out.append("(Need at least 3 completed batches for trend / outlier analysis.)")
    return "\n".join(out)


# --------------------------------------------------------------------------
# 2. Charts
# --------------------------------------------------------------------------
def plot_cost_breakdown(result: BatchResult, filename: str = None) -> str:
    """Pie chart: where does the money go?"""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{result.batch.name}_cost.png")
    # Drop zero-value slices so the pie stays readable.
    data = {k: v for k, v in result.cost_breakdown.items() if v > 0}

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(data.values(), labels=data.keys(), autopct="%1.1f%%", startangle=90)
    ax.set_title(f"Cost breakdown - {result.batch.name}\nTotal {CURRENCY}{result.total_cost:,.0f}")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_mass_balance(result: BatchResult, filename: str = None) -> str:
    """Two stacked bars (IN vs OUT) showing the streams that make each side."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{result.batch.name}_massbalance.png")
    df = result.mass_balance_df

    fig, ax = plt.subplots(figsize=(8, 6))
    for i, direction in enumerate(["IN", "OUT"]):
        bottom = 0.0
        for row in df[df["Direction"] == direction].itertuples():
            if row.Mass_kg <= 0:
                continue
            ax.bar(i, row.Mass_kg, bottom=bottom, edgecolor="white")
            # Label only segments that are big enough to hold text
            if row.Mass_kg > df["Mass_kg"].sum() * 0.02:
                ax.text(i, bottom + row.Mass_kg / 2, row.Stream, ha="center", va="center", fontsize=7)
            bottom += row.Mass_kg
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Mass IN", "Mass OUT"])
    ax.set_ylabel("kg")
    ax.set_title(f"Mass balance - {result.batch.name} (closure {result.closure_pct:.1f} %)")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_batch_comparison(df: pd.DataFrame, filename: str = None) -> str:
    """Bars = cost per kg, line = actual yield, for every stored batch."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, "batch_comparison.png")
    done = df.dropna(subset=["actual_yield"])
    if done.empty:
        raise ValueError("No completed batches (with actual output) to plot.")

    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.bar(done["batch_name"], done["cost_per_kg"], alpha=0.6)
    ax1.set_ylabel(f"Cost per kg ({CURRENCY})")
    ax1.tick_params(axis="x", rotation=45)

    ax2 = ax1.twinx()                               # second y-axis on the right
    ax2.plot(done["batch_name"], done["actual_yield"], "o-", color="darkred")
    ax2.set_ylabel("Actual yield (%)")

    ax1.set_title("Batch comparison: cost per kg vs yield")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_yield_sensitivity(batch: Batch, filename: str = None) -> str:
    """
    What-if: how does cost per kg change if the yield is different?
    We re-run the calculator for many yield values (numpy.linspace makes the range).
    """
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{batch.name}_yield_sensitivity.png")

    yields = np.linspace(50, 100, 26)               # 50, 52, 54 ... 100 %
    costs = []
    for y in yields:
        # dataclasses.replace makes a copy of the batch with only the yield changed;
        # actual_output_kg is cleared so the run is a pure "plan" calculation.
        variant = replace(batch, expected_yield_pct=float(y), actual_output_kg=None)
        costs.append(BatchCalculator(variant).calculate().cost_per_kg)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(yields, costs, "o-")
    ax.axvline(batch.expected_yield_pct, color="gray", linestyle="--", label="planned yield")
    ax.set_xlabel("Reaction yield (%)")
    ax.set_ylabel(f"Cost per kg product ({CURRENCY})")
    ax.set_title(f"Yield sensitivity - {batch.name}")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


# ==========================================================================
#  PROCESS (multi-stage) analysis - atorvastatin sheet
# ==========================================================================
def compare_process_batches(df: pd.DataFrame) -> str:
    """Text table + scipy statistics for stored process batches."""
    if df.empty:
        return "No process batches stored yet."
    cols = ["pbatch_id", "batch_name", "batch_date", "output_kg", "yield_pct",
            "steam_kg_all", "total_cost", "cost_per_kg", "e_factor"]
    out = [df[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"), ""]
    out.append(f"Average cost per kg : INR {df['cost_per_kg'].mean():,.2f}")
    out.append(f"Cheapest batch      : {df.loc[df['cost_per_kg'].idxmin(), 'batch_name']} "
               f"(INR {df['cost_per_kg'].min():,.2f}/kg)")
    out.append(f"Most expensive      : {df.loc[df['cost_per_kg'].idxmax(), 'batch_name']} "
               f"(INR {df['cost_per_kg'].max():,.2f}/kg)")
    if len(df) >= 3:
        x = np.arange(len(df))
        fit = stats.linregress(x, df["cost_per_kg"])       # is cost/kg rising or falling?
        out.append(f"Cost trend          : {fit.slope:+.2f} INR/kg per batch, R2 = {fit.rvalue**2:.2f}, p = {fit.pvalue:.3f}")
        z = stats.zscore(df["cost_per_kg"], ddof=1)          # outlier check
        bad = df.loc[np.abs(z) > 2, "batch_name"].tolist()
        out.append("Cost outliers (|z|>2): " + (", ".join(bad) if bad else "none"))
    else:
        out.append("(Need at least 3 batches for trend / outlier analysis.)")
    return "\n".join(out)


def plot_stage_loads(result: ProcessResult, filename: str = None) -> str:
    """Bar chart of the heat load of every stage (red = heating, blue = cooling)."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{result.batch.name}_stage_loads.png")
    df = result.stages_df[result.stages_df["Heat_kcal"] != 0]
    colors = ["tab:red" if q > 0 else "tab:blue" for q in df["Heat_kcal"]]

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(df["Stage"] + "\n" + df["Operation"], df["Heat_kcal"] / 1000.0, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Heat load (thousand kcal)")
    ax.set_title(f"Heat load by stage - {result.batch.name}  (red = heating, blue = cooling)")
    ax.tick_params(axis="x", labelsize=7, rotation=60)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_process_cost(result: ProcessResult, filename: str = None) -> str:
    """Stacked bars: utility cost of each stage split into equipment / refrigeration / steam."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{result.batch.name}_stage_cost.png")
    df = result.stages_df
    labels = df["Stage"] + "\n" + df["Operation"]

    fig, ax = plt.subplots(figsize=(11, 5))
    bottom = np.zeros(len(df))                       # numpy array used to stack the bars
    for col, name in [("Equip_INR", "Equipment power"), ("Refrig_INR", "Refrigeration power"),
                      ("Steam_INR", "Steam")]:
        ax.bar(labels, df[col], bottom=bottom, label=name)
        bottom += df[col].to_numpy()
    ax.set_ylabel("Cost (INR)")
    ax.set_title(f"Utility cost by stage - {result.batch.name}")
    ax.legend()
    ax.tick_params(axis="x", labelsize=7, rotation=60)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_utility_sensitivity(batch: ProcessBatch, filename: str = None) -> str:
    """Cost per kg vs electricity tariff, for three coal prices (what-if analysis)."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, f"{batch.name}_utility_sensitivity.png")
    tariffs = np.linspace(4, 14, 11)                           # INR per kWh
    coal_prices = [batch.rates.coal_inr_per_kg * f for f in (0.7, 1.0, 1.3)]

    fig, ax = plt.subplots(figsize=(7, 5))
    for coal in coal_prices:
        costs = []
        for tariff in tariffs:
            # copy the batch with new prices (dataclasses.replace) and recalculate
            rates = replace(batch.rates, electricity_inr_per_kwh=float(tariff), coal_inr_per_kg=float(coal))
            costs.append(ProcessCalculator(replace(batch, rates=rates)).calculate().cost_per_kg)
        ax.plot(tariffs, costs, "o-", label=f"coal INR {coal:.1f}/kg")
    ax.set_xlabel("Electricity tariff (INR/kWh)")
    ax.set_ylabel("Cost per kg product (INR)")
    ax.set_title(f"Utility cost sensitivity - {batch.name}")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename


def plot_process_history(df: pd.DataFrame, filename: str = None) -> str:
    """Bars = cost per kg, line = weight yield, for all stored process batches."""
    _ensure_dir()
    filename = filename or os.path.join(OUTPUT_DIR, "process_history.png")
    if df.empty:
        raise ValueError("No process batches stored.")
    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.bar(df["batch_name"], df["cost_per_kg"], alpha=0.6)
    ax1.set_ylabel("Cost per kg (INR)")
    ax1.tick_params(axis="x", rotation=45)
    ax2 = ax1.twinx()
    ax2.plot(df["batch_name"], df["yield_pct"], "o-", color="darkred")
    ax2.set_ylabel("Weight yield (%)")
    ax1.set_title("Process batch history: cost per kg vs yield")
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    return filename
