"""
regression.py — Modelo de regresión paramétrica de CAPEX unitario para obras
de transmisión eléctrica en Chile (Ley 20.936, 2016).

Variables:
- lineas: CAPEX unitario (USD/km) como función de tensión (kV), número de circuitos
  y tipo de terreno.
- subestaciones: CAPEX unitario (USD/MVA) como función de tensión y tipo de S/E.

Formas funcionales comparadas:
- log-lineal:  log(y) = β0 + β1·log(x) + Σβi·dummies  (modelo Cobb-Douglas en logs)
- log-log:     log(y) = β0 + β1·log(tensión) + β2·log(N° circuitos) + ...   (power law)
- lineal:      y       = β0 + β1·x1 + β2·x2 + ...                         (referencia)

Salida:
- Coeficientes, R², RMSE, MAPE en cada caso
- Gráfico CAPEX vs tensión con curva ajustada
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
import json
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 1. Cargar dataset consolidado
# ---------------------------------------------------------------------------
DATA = Path(__file__).parent / "dataset.csv"
FIGS = Path(__file__).parent / "figs"
FIGS.mkdir(exist_ok=True)

df = pd.read_csv(DATA)

# Filtrar líneas con datos válidos
lineas = df[df["tipo"] == "linea"].dropna(subset=["longitud_km", "tension_kv"]).copy()
lineas = lineas[lineas["longitud_km"] > 0].copy()
lineas["capex_per_km"] = lineas["capex_total_usd"] / lineas["longitud_km"]
lineas["log_tension"] = np.log(lineas["tension_kv"])
lineas["log_circuitos"] = np.log(lineas["num_circuitos"].clip(lower=1))
lineas["log_capex_km"] = np.log(lineas["capex_per_km"])

# Dummies de terreno
TERRENOS = ["urbano", "rural", "cordillera"]
for t in TERRENOS:
    lineas[f"d_{t}"] = (lineas["terreno"] == t).astype(int)

print(f"Dataset líneas: n = {len(lineas)} obras, tensión {lineas['tension_kv'].min()}-{lineas['tension_kv'].max()} kV")
print(f"CAPEX unitario rango: {lineas['capex_per_km'].min():,.0f} - {lineas['capex_per_km'].max():,.0f} USD/km")
print()

# ---------------------------------------------------------------------------
# 2. Forma funcional A — Log-lineal (Cobb-Douglas en logs)
#    log(CAPEX/km) = β0 + β1·log(tensión) + β2·log(N° circuitos) + Σβ_t·dummy(terreno)
# ---------------------------------------------------------------------------
X_cols_log = ["log_tension", "log_circuitos"] + [f"d_{t}" for t in TERRENOS]
X_log = lineas[X_cols_log].values
y_log = lineas["log_capex_km"].values

model_log = LinearRegression()
model_log.fit(X_log, y_log)
y_log_pred = model_log.predict(X_log)

r2_log = r2_score(y_log, y_log_pred)
rmse_log = np.sqrt(mean_squared_error(y_log, y_log_pred))
mape_log = np.mean(np.abs(np.exp(y_log) - np.exp(y_log_pred)) / np.exp(y_log)) * 100

print("=" * 72)
print("MODELO A — LOG-LINEAL:  log(CAPEX/km) = β0 + β1·log(kV) + β2·log(ctos) + Σβ_t·terreno")
print("=" * 72)
print(f"  R²   = {r2_log:.4f}")
print(f"  RMSE = {rmse_log:.4f}  (en log, equiv. ~{np.expm1(rmse_log)*100:.1f}% en nivel)")
print(f"  MAPE = {mape_log:.1f}%  (en nivel)")
print()
print("  Coeficientes:")
for name, c in zip(["intercepto", "β_log(kV)", "β_log(ctos)"] + [f"β_terreno={t}" for t in TERRENOS],
                   [model_log.intercept_] + list(model_log.coef_)):
    print(f"    {name:<22} {c:+.4f}")
print()

# Interpretación: elasticidad CAPEX/tensión
elasticidad_kV = model_log.coef_[0]
print(f"  → Elasticidad CAPEX/km vs tensión: {elasticidad_kV:+.3f}")
print(f"     (un aumento de 10% en kV se traduce en {10*elasticidad_kV:+.2f}% en CAPEX/km)")
print(f"  → Premio doble circuito vs simple: {(np.exp(model_log.coef_[1])-1)*100:+.1f}%")
print()

# ---------------------------------------------------------------------------
# 3. Forma funcional B — Lineal en nivel (referencia)
#    CAPEX/km = β0 + β1·tensión + β2·N° circuitos + Σβ_t·terreno
# ---------------------------------------------------------------------------
X_lin_cols = ["tension_kv", "num_circuitos"] + [f"d_{t}" for t in TERRENOS]
X_lin = lineas[X_lin_cols].values
y_lin = lineas["capex_per_km"].values

model_lin = LinearRegression()
model_lin.fit(X_lin, y_lin)
y_lin_pred = model_lin.predict(X_lin)

r2_lin = r2_score(y_lin, y_lin_pred)
rmse_lin = np.sqrt(mean_squared_error(y_lin, y_lin_pred))
mape_lin = np.mean(np.abs(y_lin - y_lin_pred) / y_lin) * 100

print("=" * 72)
print("MODELO B — LINEAL:    CAPEX/km = β0 + β1·kV + β2·ctos + Σβ_t·terreno")
print("=" * 72)
print(f"  R²   = {r2_lin:.4f}")
print(f"  RMSE = {rmse_lin:,.0f} USD/km")
print(f"  MAPE = {mape_lin:.1f}%")
print()
print("  Coeficientes:")
for name, c in zip(["intercepto", "β_kV", "β_circuitos"] + [f"β_terreno={t}" for t in TERRENOS],
                   [model_lin.intercept_] + list(model_lin.coef_)):
    print(f"    {name:<22} {c:+,.2f}")
print()

# ---------------------------------------------------------------------------
# 4. Comparación y selección
# ---------------------------------------------------------------------------
print("=" * 72)
print("COMPARACIÓN DE MODELOS")
print("=" * 72)
print(f"  {'Modelo':<14} {'R²':>8} {'RMSE':>15} {'MAPE':>8}")
print(f"  {'-'*14} {'-'*8} {'-'*15} {'-'*8}")
print(f"  {'Log-lineal':<14} {r2_log:>8.4f} {rmse_log:>15.4f} {mape_log:>7.1f}%")
print(f"  {'Lineal':<14} {r2_lin:>8.4f} {rmse_lin:>15,.0f} {mape_lin:>7.1f}%")
print()
best = "log-lineal" if r2_log >= r2_lin else "lineal"
print(f"  → Modelo recomendado: {best} (mejor R², errores más interpretables)")
print()

# ---------------------------------------------------------------------------
# 5. Subestaciones: regresión CAPEX/MVA vs tensión (referencia rápida)
# ---------------------------------------------------------------------------
ses = df[df["tipo"] == "se"].dropna(subset=["tension_kv", "capacidad_mva"]).copy()
ses = ses[ses["capacidad_mva"] > 0].copy()
ses["capex_per_mva"] = ses["capex_total_usd"] / ses["capacidad_mva"]
print("=" * 72)
print("SUBESTACIONES — Estadísticas CAPEX/MVA")
print("=" * 72)
print(f"  n = {len(ses)} obras")
print(f"  CAPEX/MVA: mediana = USD {ses['capex_per_mva'].median():,.0f} | "
      f"media = USD {ses['capex_per_mva'].mean():,.0f}")
print(f"  Rango: USD {ses['capex_per_mva'].min():,.0f} - {ses['capex_per_mva'].max():,.0f}")
print()
if len(ses) >= 3:
    Xse = ses[["tension_kv"]].values
    yse = ses["capex_per_mva"].values
    m_se = LinearRegression().fit(Xse, yse)
    print(f"  Regresión simple CAPEX/MVA ~ tensión:  pendiente = {m_se.coef_[0]:+.2f} USD/MVA por kV")
    print(f"     R² = {r2_score(yse, m_se.predict(Xse)):.3f}")
    print()

# ---------------------------------------------------------------------------
# 6. Gráfico 1: CAPEX/km vs tensión (datos + curva ajustada log-lineal)
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6.5))

colors = {"urbano": "#2E86AB", "rural": "#06A77D", "cordillera": "#D62246"}
markers = {"urbano": "o", "rural": "s", "cordillera": "^"}

for t in TERRENOS:
    sub = lineas[lineas["terreno"] == t]
    ax.scatter(sub["tension_kv"], sub["capex_per_km"] / 1000,
               s=80, alpha=0.75, c=colors[t], marker=markers[t],
               edgecolor="white", linewidth=1.2,
               label=f"{t.title()} (n={len(sub)})")

# Curva ajustada del modelo log-lineal, fijando rural como referencia
tension_grid = np.linspace(50, 800, 200)
ctos_ref = 1
X_curve = np.column_stack([
    np.log(tension_grid),
    np.log(np.full_like(tension_grid, ctos_ref)),
    np.ones_like(tension_grid),  # rural
    np.zeros_like(tension_grid),  # urbano
    np.zeros_like(tension_grid),  # cordillera
])
y_curve = np.exp(model_log.predict(X_curve))
ax.plot(tension_grid, y_curve / 1000, "k-", linewidth=2, alpha=0.7,
        label=f"Curva log-lineal (1 cto, rural)  R²={r2_log:.3f}")

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("Tensión nominal (kV, escala log)", fontsize=12)
ax.set_ylabel("CAPEX unitario (miles USD/km, escala log)", fontsize=12)
ax.set_title("CAPEX unitario de líneas de transmisión — Chile y benchmarks\n"
             "Modelo log-lineal ajustado (n={} obras)".format(len(lineas)),
             fontsize=13, fontweight="bold")
ax.grid(True, which="both", alpha=0.3, linestyle="--")
ax.legend(loc="lower right", fontsize=10, framealpha=0.95)
ax.text(0.02, 0.97,
        f"Modelo log-lineal:\n  β log(kV)   = {model_log.coef_[0]:+.3f}\n"
        f"  β log(ctos)= {model_log.coef_[1]:+.3f}\n"
        f"  R² = {r2_log:.3f}\n  MAPE = {mape_log:.0f}%",
        transform=ax.transAxes, va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.9),
        fontsize=9, family="monospace")
plt.tight_layout()
plt.savefig(FIGS / "capex_vs_tension.png", dpi=140, bbox_inches="tight")
plt.close()
print(f"  ✓ Figura guardada: {FIGS / 'capex_vs_tension.png'}")
print()

# ---------------------------------------------------------------------------
# 7. Resumen JSON para downstream
# ---------------------------------------------------------------------------
summary = {
    "n_lineas": int(len(lineas)),
    "n_ses": int(len(ses)),
    "modelo_recomendado": best,
    "log_lineal": {
        "r2": float(r2_log),
        "rmse_log": float(rmse_log),
        "mape_pct": float(mape_log),
        "intercepto": float(model_log.intercept_),
        "coef_log_tension": float(model_log.coef_[0]),
        "coef_log_circuitos": float(model_log.coef_[1]),
        "coef_terreno": {t: float(model_log.coef_[2 + i]) for i, t in enumerate(TERRENOS)},
    },
    "lineal": {
        "r2": float(r2_lin),
        "rmse_usd_km": float(rmse_lin),
        "mape_pct": float(mape_lin),
        "intercepto": float(model_lin.intercept_),
        "coef_tension_kv": float(model_lin.coef_[0]),
        "coef_circuitos": float(model_lin.coef_[1]),
        "coef_terreno": {t: float(model_lin.coef_[2 + i]) for i, t in enumerate(TERRENOS)},
    },
    "se_capex_por_mva_mediana_usd": float(ses["capex_per_mva"].median()),
    "se_capex_por_mva_p25_usd": float(ses["capex_per_mva"].quantile(0.25)),
    "se_capex_por_mva_p75_usd": float(ses["capex_per_mva"].quantile(0.75)),
}

with open(FIGS / "regression_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"  ✓ Resumen JSON: {FIGS / 'regression_summary.json'}")
print()
print("=" * 72)
print("Listo. Resultados en /workspace/modelador/figs/")
print("=" * 72)
