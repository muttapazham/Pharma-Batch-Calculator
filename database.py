"""
database.py
===========
Stores batch records in an SQL database so we can look at them later
and compare batches over time.

We use SQLite because it ships with Python (no installation needed) and
keeps everything in a single file: batch_records.db

Tables:
    batches          -> one row per stoichiometric batch (summary numbers)
    batch_materials  -> many rows per batch (each material charged)
                        linked to batches by batch_id (a FOREIGN KEY)
    process_batches  -> one row per multi-stage process batch (atorvastatin sheet)
    process_stages   -> one row per stage, linked to process_batches (FOREIGN KEY)
    material_prices  -> raw-material price list, reused by every process run
"""

import sqlite3
from contextlib import contextmanager
from typing import Optional

import pandas as pd

from calculator import BatchResult
from process_calculator import ProcessResult


class BatchDatabase:
    def __init__(self, path: str = "batch_records.db"):
        self.path = path
        self._create_tables()

    # -- connection helper --------------------------------------------------
    @contextmanager
    def _session(self):
        """Open a connection, commit on success, roll back on error, always close."""
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")   # make FOREIGN KEY rules actually work
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- schema -------------------------------------------------------------
    def _create_tables(self):
        with self._session() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_name        TEXT NOT NULL,
                    batch_date        TEXT NOT NULL,
                    reaction_name     TEXT,
                    product_name      TEXT,
                    target_kg         REAL,
                    expected_yield    REAL,
                    actual_output_kg  REAL,     -- NULL if batch not run yet
                    actual_yield      REAL,     -- NULL if batch not run yet
                    raw_material_cost REAL,
                    solvent_cost      REAL,
                    labor_cost        REAL,
                    utility_cost      REAL,
                    overhead_cost     REAL,
                    total_cost        REAL,
                    cost_per_kg       REAL,
                    e_factor          REAL,
                    atom_economy      REAL,
                    closure_pct       REAL
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_materials (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id  INTEGER NOT NULL
                              REFERENCES batches(batch_id) ON DELETE CASCADE,
                    material  TEXT,
                    kind      TEXT,
                    mass_kg   REAL,
                    cost      REAL
                )""")

            # ---- Tables for the multi-stage PROCESS calculator (atorvastatin sheet) ----
            conn.execute("""
                CREATE TABLE IF NOT EXISTS process_batches (
                    pbatch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_name       TEXT NOT NULL,
                    product_name     TEXT,
                    batch_date       TEXT,
                    key_input_kg     REAL,
                    output_kg        REAL,
                    yield_pct        REAL,
                    heat_kcal        REAL,
                    steam_kg_all     REAL,
                    steam_kg_reactor REAL,
                    chw_tr           REAL,
                    brine_tr         REAL,
                    equip_cost       REAL,
                    refrig_cost      REAL,
                    steam_cost       REAL,
                    raw_cost         REAL,
                    total_cost       REAL,
                    cost_per_kg      REAL,
                    e_factor         REAL
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS process_stages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pbatch_id   INTEGER NOT NULL
                                REFERENCES process_batches(pbatch_id) ON DELETE CASCADE,
                    stage       TEXT,
                    equipment   TEXT,
                    operation   TEXT,
                    time_hr     REAL,
                    heat_kcal   REAL,
                    steam_kg    REAL,
                    chw_tr      REAL,
                    brine_tr    REAL,
                    power_kw    REAL,
                    equip_cost  REAL,
                    refrig_cost REAL,
                    steam_cost  REAL,
                    total_cost  REAL
                )""")
            # Raw material prices are typed in once and reused by every run
            conn.execute("""
                CREATE TABLE IF NOT EXISTS material_prices (
                    material      TEXT PRIMARY KEY,
                    price_per_kg  REAL NOT NULL
                )""")

    # -- CREATE -------------------------------------------------------------
    def save_result(self, r: BatchResult) -> int:
        """Save one calculated batch. Returns the new batch_id."""
        b = r.batch
        actual_yield = None if r.actual_yield_pct != r.actual_yield_pct else r.actual_yield_pct  # NaN check
        cb = r.cost_breakdown
        with self._session() as conn:
            # "?" placeholders protect us from SQL injection - never build SQL with f-strings.
            cur = conn.execute("""
                INSERT INTO batches (batch_name, batch_date, reaction_name, product_name,
                    target_kg, expected_yield, actual_output_kg, actual_yield,
                    raw_material_cost, solvent_cost, labor_cost, utility_cost, overhead_cost,
                    total_cost, cost_per_kg, e_factor, atom_economy, closure_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (b.name, b.batch_date, b.reaction.name, b.reaction.product.name,
                 b.target_output_kg, b.expected_yield_pct, b.actual_output_kg, actual_yield,
                 cb["Raw materials"], cb["Solvents (net)"], cb["Labour"], cb["Utilities"],
                 cb["Overhead"], r.total_cost, r.cost_per_kg, r.e_factor,
                 r.atom_economy_pct, r.closure_pct))
            batch_id = cur.lastrowid

            # One row per material charged
            conn.executemany(
                "INSERT INTO batch_materials (batch_id, material, kind, mass_kg, cost) VALUES (?,?,?,?,?)",
                [(batch_id, row.Material, row.Kind, row.Mass_kg, row.Cost)
                 for row in r.materials_df.itertuples()])
        return batch_id

    # -- READ ---------------------------------------------------------------
    def list_batches(self) -> pd.DataFrame:
        """All batches, oldest first, as a pandas DataFrame."""
        with self._session() as conn:
            return pd.read_sql_query("SELECT * FROM batches ORDER BY batch_date, batch_id", conn)

    def get_batch(self, batch_id: int) -> Optional[pd.Series]:
        """One batch summary row, or None if it does not exist."""
        with self._session() as conn:
            df = pd.read_sql_query("SELECT * FROM batches WHERE batch_id = ?", conn, params=(batch_id,))
        return None if df.empty else df.iloc[0]

    def get_materials(self, batch_id: int) -> pd.DataFrame:
        """The materials list of one batch."""
        with self._session() as conn:
            return pd.read_sql_query(
                "SELECT material, kind, mass_kg, cost FROM batch_materials WHERE batch_id = ?",
                conn, params=(batch_id,))

    def find_by_product(self, product_name: str) -> pd.DataFrame:
        """Historical retrieval: every batch made for one product."""
        with self._session() as conn:
            return pd.read_sql_query(
                "SELECT * FROM batches WHERE product_name LIKE ? ORDER BY batch_date, batch_id",
                conn, params=(f"%{product_name}%",))

    # -- UPDATE -------------------------------------------------------------
    def update_actual_output(self, batch_id: int, actual_kg: float) -> bool:
        """
        Record the real output after the batch is finished, and recompute the
        actual yield and cost per kg. Returns False if batch_id was not found.
        """
        with self._session() as conn:
            row = conn.execute(
                "SELECT target_kg, expected_yield, total_cost FROM batches WHERE batch_id = ?",
                (batch_id,)).fetchone()
            if row is None:
                return False
            target, exp_yield, total_cost = row
            theoretical = target / (exp_yield / 100.0)
            if actual_kg > theoretical:
                raise ValueError("Actual output cannot exceed the theoretical yield")
            conn.execute(
                "UPDATE batches SET actual_output_kg=?, actual_yield=?, cost_per_kg=? WHERE batch_id=?",
                (actual_kg, actual_kg / theoretical * 100.0, total_cost / actual_kg, batch_id))
        return True

    # -- DELETE -------------------------------------------------------------
    def delete_batch(self, batch_id: int) -> bool:
        """Delete a batch (its materials are deleted automatically - ON DELETE CASCADE)."""
        with self._session() as conn:
            cur = conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
            return cur.rowcount > 0

    # ======================================================================
    #  PROCESS (multi-stage) records
    # ======================================================================
    def save_process_result(self, r: ProcessResult) -> int:
        """Save a calculated process batch and all of its stages. Returns pbatch_id."""
        b, t, cb = r.batch, r.totals, r.cost_breakdown
        costs = list(cb.values())     # equipment, refrigeration, steam, raw materials (in this order)
        with self._session() as conn:
            cur = conn.execute("""
                INSERT INTO process_batches (batch_name, product_name, batch_date, key_input_kg,
                    output_kg, yield_pct, heat_kcal, steam_kg_all, steam_kg_reactor, chw_tr, brine_tr,
                    equip_cost, refrig_cost, steam_cost, raw_cost, total_cost, cost_per_kg, e_factor)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (b.name, b.product_name, b.batch_date, b.key_input_kg, b.output_kg, r.yield_pct,
                 t["heat_kcal"], t["steam_kg"], t["steam_reactor_kg"], t["chw_tr"], t["brine_tr"],
                 costs[0], costs[1], costs[2], costs[3], r.total_cost, r.cost_per_kg, r.e_factor))
            pid = cur.lastrowid
            conn.executemany("""
                INSERT INTO process_stages (pbatch_id, stage, equipment, operation, time_hr, heat_kcal,
                    steam_kg, chw_tr, brine_tr, power_kw, equip_cost, refrig_cost, steam_cost, total_cost)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(pid, s.Stage, s.Equipment, s.Operation, s.Time_hr, s.Heat_kcal, s.Steam_kg, s.CHW_TR,
                  s.Brine_TR, s.Power_kW, s.Equip_INR, s.Refrig_INR, s.Steam_INR, s.Total_INR)
                 for s in r.stages_df.itertuples()])
        return pid

    def list_process_batches(self) -> pd.DataFrame:
        with self._session() as conn:
            return pd.read_sql_query(
                "SELECT * FROM process_batches ORDER BY batch_date, pbatch_id", conn)

    def get_process_stages(self, pbatch_id: int) -> pd.DataFrame:
        with self._session() as conn:
            return pd.read_sql_query(
                "SELECT stage, equipment, operation, time_hr, heat_kcal, steam_kg, chw_tr, brine_tr, "
                "power_kw, total_cost FROM process_stages WHERE pbatch_id = ? ORDER BY id",
                conn, params=(pbatch_id,))

    def stage_cost_history(self, operation: str) -> pd.DataFrame:
        """SQL JOIN example: cost of one type of operation across all stored batches."""
        with self._session() as conn:
            return pd.read_sql_query("""
                SELECT b.batch_name, b.batch_date, s.stage, s.equipment, s.total_cost
                FROM process_stages s JOIN process_batches b ON b.pbatch_id = s.pbatch_id
                WHERE s.operation = ? ORDER BY b.batch_date, s.id""", conn, params=(operation,))

    def delete_process_batch(self, pbatch_id: int) -> bool:
        with self._session() as conn:
            return conn.execute("DELETE FROM process_batches WHERE pbatch_id = ?", (pbatch_id,)).rowcount > 0

    # -- raw material prices ---------------------------------------------
    def set_price(self, material: str, price_per_kg: float):
        """Insert or update a raw-material price (UPSERT)."""
        if price_per_kg < 0:
            raise ValueError("Price cannot be negative")
        with self._session() as conn:
            conn.execute("""INSERT INTO material_prices (material, price_per_kg) VALUES (?, ?)
                            ON CONFLICT(material) DO UPDATE SET price_per_kg = excluded.price_per_kg""",
                         (material, price_per_kg))

    def get_prices(self) -> dict:
        """All saved prices as {material name: INR per kg}."""
        with self._session() as conn:
            return dict(conn.execute("SELECT material, price_per_kg FROM material_prices").fetchall())
