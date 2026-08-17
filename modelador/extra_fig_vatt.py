"""Genera la figura del VATT anualizado por separado."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from montecarlo import simular_obra, ESCENARIOS

FIGS = Path(__file__).parent / "figs"

# Escenario principal
params = ESCENARIOS["linea_500_doble_cordillera"]
sim = simular_obra(**params, n=10_000, seed=20260720)

fig, ax = plt.subplots(figsize=(9, 6))
vatt_mm = sim["vatt_usd_anual"] / 1e6
ax.hist(vatt_mm, bins=60, color="#06A77D", alpha=0.75, edgecolor="white")
for q, c, ls in [(0.50, "#2E86AB", "-"), (0.75, "#F18F01", "--"), (0.90, "#D62246", "--")]:
    v = np.quantile(vatt_mm, q)
    ax.axvline(v, color=c, linestyle=ls, linewidth=2,
               label=f"P{int(q*100)} = USD {v:,.1f} MM/año")
ax.set_xlabel("VATT anualizado (millones USD/año)", fontsize=12)
ax.set_ylabel("Frecuencia (de 10.000 simulaciones)", fontsize=11)
ax.set_title(
    "Distribución del VATT — Línea 2x500 kV, 200 km, cordillera\n"
    "Metodología CNE (Ley 20.936) — Tasa 6% real, vida útil 30a, COMA 1.5-3.5%",
    fontsize=12, fontweight="bold",
)
ax.legend(loc="upper right", fontsize=11)
ax.grid(True, alpha=0.3, linestyle="--")
plt.tight_layout()
plt.savefig(FIGS / "montecarlo_vatt.png", dpi=140, bbox_inches="tight")
print(f"✓ {FIGS / 'montecarlo_vatt.png'}")
