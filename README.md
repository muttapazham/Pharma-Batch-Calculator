# Pharma Batch Cost & Mass Balance Calculator

Python project (modular OOP + SQL storage) with two calculators:

1. **Atorvastatin Calcium process** - a multi-stage production process typed in from the
   plant sheet (heating, distillation, cooling, centrifuge, dryers, pulveriser).
   Calculates heat loads, steam, chilled water / brine, power, utility cost, raw-material
   requirements, yield, mass balance and E-factor - and checks itself against the sheet.
2. **Generic stoichiometric batch** - raw-material requirements from a balanced equation
   (paracetamol demo included).

## Files
| File | Job |
|------|-----|
| `process_models.py`     | Data classes: StageMaterial, ProcessStage, UtilityRates, ProcessBatch |
| `atorvastatin_data.py`  | The atorvastatin sheet as Python data (+ the sheet's printed values for checking) |
| `process_calculator.py` | Heat load / steam / refrigeration / cost / mass balance / validation |
| `models.py`, `calculator.py` | Generic stoichiometric batch (classes + maths) |
| `database.py`           | SQLite storage for both calculators + raw-material price list |
| `analysis.py`           | pandas / scipy comparison and matplotlib charts |
| `main.py`               | Menu program (start here) |

## Run
```
pip install -r requirements.txt
python main.py
```
Menu 1 -> option 1 (report), 2 (check against the sheet), 4 (enter raw-material prices),
3 (run for another batch size and save), 9 (simulated history), 7 (compare), 8 (charts).
Charts go to `plots/`; the database is `batch_records.db`.

## Formulas (reproduced from the sheet)
| Item | Formula |
|------|---------|
| Heating / cooling heat | `Q = mass x Cp_mix x (T_final - T_init)` |
| Distillation heat | `Q = kg distilled x 263 kcal/kg` |
| Drying heat | `Q = kg evaporated x 540 (+ sensible heat if temperatures given)` |
| Steam | `Q / 540` kg |
| Cooling refrigeration | `|Q| / time / 3024 x 1.5` TR (brine if final temp < 15 C, else chilled water) |
| Condenser refrigeration | `Q / 3024` TR, 90 % chilled water + 10 % brine |
| Refrigeration power | `TR x 3.5` kW |
| Electricity cost | `kW x hours x 8 INR/kWh` |
| Steam cost | `steam kg x (coal 8.8 INR/kg / 5 kg steam per kg coal)` |

All rates are in `UtilityRates` (`process_models.py`) and can be changed.

## Assumptions to be aware of
* Raw-material prices are **not** in the sheet. Enter them in menu option 4; until then
  the raw-material cost is reported as incomplete.
* "5 kg steam per kg coal" is back-calculated from the sheet's 13.0 INR/kg steam cost.
* Row 41 (rotary vacuum dryer) has no temperatures in the sheet; 30 -> 75 C is inferred
  because it reproduces the sheet's 23,434 kcal exactly.
* Yield is a weight yield (210 kg product / 225 kg ATI); molar yield would need the molar masses.
* Option 9 (history) creates SIMULATED example runs, not real plant data.
