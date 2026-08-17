"""
montecarlo.py — Simulador Monte Carlo de CAPEX y VATT de nuevas obras de
transmisión eléctrica bajo la metodología CNE (Ley 20.936).

Para una "obra tipo" configurable, perturba:
- Costo unitario base (lognormal, calibrada con los coeficientes de regression.py)
- Tipo de terreno (categórico con probabilidades)
- Longitud (triangular ±20%)
- Contingencias (PERT con cola larga)
- Vida útil y tasa regulatoria (uniforme en rango histórico)

Calcula:
- CAPEX P10, P50, P75, P90 (intervalo 80%)
- VATT anualizado P10, P50, P75, P90
- AVI (Valor de Inversión), COMA

Salida:
- reportable.csv con resultados por escenario
- 2 figuras (histogramas CAPEX y VATT)
- txt con resumen ejecutivo

Uso:
    python montecarlo.py                              # corre los 3 escenarios por defecto
    python montecarlo.py --escenario linea_500_doble
    python montecarlo.py --custom --kv 220 --ctos 1 --km 100 --terreno rural
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reproducibilidad
RNG = np.random.default_rng(seed=20260720)

# ---------------------------------------------------------------------------
# Parámetros regulatorios CNE (defaults calibrados con la última metodología)
# ---------------------------------------------------------------------------
TASA_REGULATORIA = 0.06       # 6% real anual (Res. Exenta CNE vigente 2020-2023)
TASA_FALLBACK    = 0.10       # 10% real anual (procesos previos 2014-2019)
VIDA_UTIL_LINEA  = 30         # años
VIDA_UTIL_SE     = 25         # años
COMA_PCT_DEFAULT = 0.025      # 2.5% del AVI anual (rango histórico 1.5-3.5%)

# Costos unitarios BASE (mediana por tensión/terreno, USD/km) — calibrados con
# regression.py y benchmarks World Bank / ACER / CNE ITP 2022.
COSTO_BASE_USD_POR_KM = {
    66:   110_000,
    110:  150_000,
    138:  200_000,
    154:  220_000,
    220:  300_000,
    230:  330_000,
    345:  500_000,
    500:  850_000,
    600:  900_000,  # HVDC
    765:  1_500_000,
}

# Multiplicador por terreno (relativo a rural=1.0)
MULT_TERRENO = {
    "urbano":      1.45,   # +45% por servidumbres urbanas, espacio, ruido
    "rural":       1.00,   # base
    "cordillera":  1.25,   # +25% por accesos difíciles, altura, fundaciones
}

# Mult. doble circuito
MULT_DOBLE_CTO = 1.45

# Probabilidades a priori del terreno (distribución categórica con pesos)
P_TERRENO = {
    "rural":      0.55,
    "cordillera": 0.30,
    "urbano":     0.15,
}

# Volatilidad del costo unitario (coef. de variación lognormal)
CV_COSTO_UNITARIO = 0.22   # ±22% ~1σ

# Volatilidad de longitud
VAR_LONGITUD_PCT = 0.20     # ±20%

# PERT para contingencias (optimista / más probable / pesimista)
PERT_OPT  = 1.00   # 0% adicional
PERT_MODE = 1.12   # +12% (contingencias estándar CNE)
PERT_PESS = 1.45   # +45% (cola larga)


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------
def anualidad(avi: float, tasa: float, vida: int) -> float:
    """Anualidad estándar de un AVI con tasa real y vida útil."""
    if tasa <= 0 or vida <= 0:
        return avi / max(vida, 1)
    return avi * tasa / (1.0 - (1.0 + tasa) ** (-vida))


def pert_sample(rng: np.random.Generator, n: int, o: float, m: float, p: float) -> np.ndarray:
    """Distribución PERT (Beta-PERT)."""
    # PERT clásico con mu = (o + 4m + p) / 6
    mu = (o + 4 * m + p) / 6.0
    if mu <= 0:
        return np.ones(n)
    alpha = 1 + 4 * (m - o) / (p - o) if p > o else 4
    beta = 1 + 4 * (p - m) / (p - o) if p > o else 4
    return o + (p - o) * rng.beta(max(alpha, 0.1), max(beta, 0.1), size=n)


def lognormal_cv(rng: np.random.Generator, mu_level: float, cv: float, n: int) -> np.ndarray:
    """Lognormal con media = mu_level, coef. de variación = cv."""
    sigma2 = np.log(1 + cv ** 2)
    sigma = np.sqrt(sigma2)
    mu = np.log(mu_level) - 0.5 * sigma2
    return rng.lognormal(mean=mu, sigma=sigma, size=n)


# ---------------------------------------------------------------------------
# Simulación de una obra tipo
# ---------------------------------------------------------------------------
def simular_obra(
    kv: int,
    num_circuitos: int,
    longitud_km: float,
    terreno_in: str,
    capacidad_mva: float = 0.0,
    n: int = 10_000,
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Devuelve un DataFrame con n simulaciones de:
    - costo_unitario_usd_km, longitud_km_real, contingencia_mult
    - capex_total_usd, avi_usd, coma_usd, vatt_usd_anual
    """
    rng = np.random.default_rng(seed) if seed is not None else RNG

    # 1) Costo unitario base (lognormal)
    base = COSTO_BASE_USD_POR_KM.get(kv, COSTO_BASE_USD_POR_KM[220])
    if num_circuitos >= 2:
        base *= MULT_DOBLE_CTO
    base *= MULT_TERRENO.get(terreno_in, 1.0)
    costo_unit = lognormal_cv(rng, base, CV_COSTO_UNITARIO, n)

    # 2) Variabilidad del terreno (algunos proyectos cambian de categoría)
    if terreno_in == "mix":
        terrenos = list(P_TERRENO.keys())
        probs = list(P_TERRENO.values())
        idx = rng.choice(len(terrenos), size=n, p=probs)
        mult_terreno = np.array([MULT_TERRENO[t] for t in terrenos])[idx]
        # Reescalar costo unitario al terreno efectivo (se resta el efecto del "mix" base=1.0)
        costo_unit = costo_unit / 1.0 * mult_terreno
    else:
        mult_terreno = np.full(n, MULT_TERRENO.get(terreno_in, 1.0))

    # 3) Variabilidad de longitud (triangular ±20%)
    if longitud_km > 0:
        long_min = longitud_km * (1 - VAR_LONGITUD_PCT)
        long_mode = longitud_km
        long_max = longitud_km * (1 + VAR_LONGITUD_PCT)
        longitud_real = rng.triangular(long_min, long_mode, long_max, size=n)
    else:
        # S/E: capacidad (MVA) puede variar ±10%
        longitud_real = np.zeros(n)

    # 4) Contingencias (PERT con cola larga)
    conting = pert_sample(rng, n, PERT_OPT, PERT_MODE, PERT_PESS)

    # 5) CAPEX total
    if longitud_km > 0:
        # Línea
        capex = costo_unit * longitud_real * conting
    else:
        # S/E: CAPEX/MVA perturbado
        base_se_per_mva = 45_000  # USD/MVA, mediana del dataset
        if kv >= 500:
            base_se_per_mva = 65_000
        if "GIS" in terreno_in.upper() or terreno_in == "urbano":
            base_se_per_mva *= 1.6  # prima GIS
        per_mva = lognormal_cv(rng, base_se_per_mva, 0.30, n)
        cap_real_mva = capacidad_mva * rng.triangular(0.90, 1.0, 1.10, size=n)
        capex = per_mva * cap_real_mva * conting

    # 6) Tasa de descuento (uniforme entre 6% y 10%, valor CNE real)
    tasa = rng.uniform(TASA_REGULATORIA, TASA_FALLBACK, size=n)

    # 7) Vida útil (con algo de dispersión: ±2 años)
    vida = (VIDA_UTIL_LINEA if longitud_km > 0 else VIDA_UTIL_SE) + rng.choice([-2, 0, 2], size=n)

    # 8) COMA (uniforme 1.5-3.5%)
    coma_pct = rng.uniform(0.015, 0.035, size=n)

    # 9) AVI y VATT
    avi = capex
    anual = np.array([anualidad(avi[i], tasa[i], vida[i]) for i in range(n)])
    coma = avi * coma_pct
    vatt = anual + coma

    return pd.DataFrame({
        "costo_unitario_usd_km": costo_unit,
        "longitud_km_real": longitud_real,
        "contingencia": conting,
        "capex_total_usd": capex,
        "tasa_descuento": tasa,
        "vida_util_anos": vida,
        "coma_pct": coma_pct,
        "avi_usd": avi,
        "coma_anual_usd": coma,
        "vatt_usd_anual": vatt,
    })


# ---------------------------------------------------------------------------
# Escenarios predefinidos
# ---------------------------------------------------------------------------
ESCENARIOS = {
    "linea_500_doble_cordillera": dict(
        kv=500, num_circuitos=2, longitud_km=200, terreno_in="cordillera", capacidad_mva=0,
    ),
    "linea_220_simple_rural": dict(
        kv=220, num_circuitos=1, longitud_km=80, terreno_in="rural", capacidad_mva=0,
    ),
    "se_500_220_gis_urbana": dict(
        kv=500, num_circuitos=0, longitud_km=0, terreno_in="GIS_urbana", capacidad_mva=500,
    ),
    "linea_220_doble_mix": dict(
        kv=220, num_circuitos=2, longitud_km=120, terreno_in="mix", capacidad_mva=0,
    ),
    "hvdc_600_bipolar": dict(
        kv=600, num_circuitos=1, longitud_km=1300, terreno_in="cordillera", capacidad_mva=3000,
    ),
}


def resumen(df_sim: pd.DataFrame, escenario: str) -> dict:
    p = lambda q: float(np.quantile(df_sim["capex_total_usd"], q))
    v = lambda q: float(np.quantile(df_sim["vatt_usd_anual"], q))
    return {
        "escenario": escenario,
        "n": len(df_sim),
        "capex_p10_usd": p(0.10),
        "capex_p50_usd": p(0.50),
        "capex_p75_usd": p(0.75),
        "capex_p90_usd": p(0.90),
        "capex_media_usd": float(df_sim["capex_total_usd"].mean()),
        "vatt_p10_usd": v(0.10),
        "vatt_p50_usd": v(0.50),
        "vatt_p75_usd": v(0.75),
        "vatt_p90_usd": v(0.90),
        "vatt_media_usd": float(df_sim["vatt_usd_anual"].mean()),
        "vatt_p10_p90_banda_pct": float((v(0.90) - v(0.10)) / v(0.50) * 100),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10_000, help="número de simulaciones Monte Carlo")
    parser.add_argument("--escenario", type=str, default=None,
                        help="nombre de un escenario predefinido")
    parser.add_argument("--custom", action="store_true",
                        help="usar --kv --ctos --km --terreno --mva")
    parser.add_argument("--kv", type=int, default=220)
    parser.add_argument("--ctos", type=int, default=1)
    parser.add_argument("--km", type=float, default=100)
    parser.add_argument("--terreno", type=str, default="rural",
                        choices=list(MULT_TERRENO.keys()) + ["mix", "GIS_urbana"])
    parser.add_argument("--mva", type=float, default=0)
    parser.add_argument("--seed", type=int, default=20260720)
    args = parser.parse_args()

    FIGS = Path(__file__).parent / "figs"
    FIGS.mkdir(exist_ok=True)

    if args.custom:
        escenarios_a_correr = {"custom": dict(
            kv=args.kv, num_circuitos=args.ctos, longitud_km=args.km,
            terreno_in=args.terreno, capacidad_mva=args.mva,
        )}
    elif args.escenario:
        escenarios_a_correr = {args.escenario: ESCENARIOS[args.escenario]}
    else:
        escenarios_a_correr = ESCENARIOS

    print("=" * 78)
    print(f"MONTE CARLO — CAPEX & VATT de nuevas obras de transmisión (Ley 20.936)")
    print(f"N = {args.n:,} simulaciones por escenario | semilla = {args.seed}")
    print(f"Tasa regulatoria: {TASA_REGULATORIA*100:.0f}% real (rango 6-10%) | "
          f"COMA: 1.5-3.5% del AVI | Vida útil: 30a líneas, 25a S/E")
    print("=" * 78)
    print()

    resumen_rows = []
    for nombre, params in escenarios_a_correr.items():
        print(f"▶ Escenario: {nombre}")
        print(f"   {params}")
        sim = simular_obra(**params, n=args.n, seed=args.seed)
        r = resumen(sim, nombre)
        resumen_rows.append(r)

        # Imprimir resumen
        if params["longitud_km"] > 0:
            print(f"   CAPEX: P50 = USD {r['capex_p50_usd']/1e6:,.1f} MM | "
                  f"P75 = {r['capex_p75_usd']/1e6:,.1f} MM | P90 = {r['capex_p90_usd']/1e6:,.1f} MM")
            print(f"   VATT:  P50 = USD {r['vatt_p50_usd']/1e6:,.2f} MM/año | "
                  f"P90 = {r['vatt_p90_usd']/1e6:,.2f} MM/año")
        else:
            print(f"   CAPEX: P50 = USD {r['capex_p50_usd']/1e6:,.2f} MM | "
                  f"P90 = {r['capex_p90_usd']/1e6:,.2f} MM")
            print(f"   VATT:  P50 = USD {r['vatt_p50_usd']/1e3:,.1f} k/año | "
                  f"P90 = {r['vatt_p90_usd']/1e3:,.1f} k/año")
        print(f"   Banda P10-P90 VATT: ±{r['vatt_p10_p90_banda_pct']/2:.0f}% sobre P50")
        print()

    df_resumen = pd.DataFrame(resumen_rows)
    out_csv = Path(__file__).parent / "reportable.csv"
    df_resumen.to_csv(out_csv, index=False)
    print(f"  ✓ Tabla resumen: {out_csv}")
    print()

    # -----------------------------------------------------------------------
    # Figuras: histograma CAPEX y VATT (escenario principal)
    # -----------------------------------------------------------------------
    main_esc = list(escenarios_a_correr.keys())[0]
    sim_main = simular_obra(**escenarios_a_correr[main_esc], n=args.n, seed=args.seed)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    # CAPEX
    ax = axes[0]
    capex_mm = sim_main["capex_total_usd"] / 1e6
    ax.hist(capex_mm, bins=60, color="#2E86AB", alpha=0.75, edgecolor="white")
    for q, c, ls in [(0.50, "#06A77D", "-"), (0.75, "#F18F01", "--"), (0.90, "#D62246", "--")]:
        v = np.quantile(capex_mm, q)
        ax.axvline(v, color=c, linestyle=ls, linewidth=2,
                   label=f"P{int(q*100)} = {v:,.1f} MM USD")
    ax.set_xlabel("CAPEX total (millones USD)", fontsize=11)
    ax.set_ylabel("Frecuencia (de {} simulaciones)".format(args.n), fontsize=11)
    ax.set_title(f"Distribución del CAPEX — {main_esc}", fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3, linestyle="--")

    # VATT
    ax = axes[1]
    if sim_main["vatt_usd_anual"].median() > 1e6:
        vatt_mm = sim_main["vatt_usd_anual"] / 1e6
        xlabel = "VATT anualizado (millones USD/año)"
    else:
        vatt_mm = sim_main["vatt_usd_anual"] / 1e3
        xlabel = "VATT anualizado (miles USD/año)"
    ax.hist(vatt_mm, bins=60, color="#06A77D", alpha=0.75, edgecolor="white")
    for q, c, ls in [(0.50, "#2E86AB", "-"), (0.75, "#F18F01", "--"), (0.90, "#D62246", "--")]:
        v = np.quantile(vatt_mm, q)
        ax.axvline(v, color=c, linestyle=ls, linewidth=2,
                   label=f"P{int(q*100)} = {v:,.2f}")
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Frecuencia", fontsize=11)
    ax.set_title(f"Distribución del VATT — {main_esc}", fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3, linestyle="--")

    plt.suptitle(f"Simulación Monte Carlo (N = {args.n:,})", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_fig = FIGS / "montecarlo_resultados.png"
    plt.savefig(out_fig, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  ✓ Figura CAPEX+VATT: {out_fig}")

    # -----------------------------------------------------------------------
    # Gráfico adicional: dispersión estimado vs observado (estilo informe)
    # -----------------------------------------------------------------------
    DATA = Path(__file__).parent / "dataset.csv"
    df = pd.read_csv(DATA)
    lineas = df[df["tipo"] == "linea"].dropna(subset=["longitud_km"]).copy()
    lineas = lineas[lineas["longitud_km"] > 0].copy()
    lineas["capex_obs_km"] = lineas["capex_total_usd"] / lineas["longitud_km"] / 1000  # miles USD/km

    # Predicción con el modelo log-lineal (reentrenado aquí, simplificado)
    from sklearn.linear_model import LinearRegression
    df_reg = lineas.copy()
    df_reg["log_t"] = np.log(df_reg["tension_kv"])
    df_reg["log_c"] = np.log(df_reg["num_circuitos"].clip(lower=1))
    df_reg["log_y"] = np.log(df_reg["capex_obs_km"])
    for t in ["urbano", "rural", "cordillera"]:
        df_reg[f"d_{t}"] = (df_reg["terreno"] == t).astype(int)
    X = df_reg[["log_t", "log_c"] + [f"d_{t}" for t in ["urbano", "rural", "cordillera"]]].values
    y = df_reg["log_y"].values
    m = LinearRegression().fit(X, y)
    capex_pred_km = np.exp(m.predict(X)) * 1000  # USD/km

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.scatter(lineas["capex_obs_km"], capex_pred_km / 1000,
               s=80, alpha=0.75, c="#2E86AB", edgecolor="white", linewidth=1.2)
    lo = min(lineas["capex_obs_km"].min(), capex_pred_km.min() / 1000) * 0.5
    hi = max(lineas["capex_obs_km"].max(), capex_pred_km.max() / 1000) * 1.5
    ax.plot([lo, hi], [lo, hi], "k-", linewidth=1.5, label="Estimado = Observado")
    ax.fill_between([lo, hi], [lo * 0.75, hi * 0.75], [lo * 1.25, hi * 1.25],
                    color="gray", alpha=0.15, label="Banda ±25%")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("CAPEX observado (miles USD/km)", fontsize=12)
    ax.set_ylabel("CAPEX estimado por regresión log-lineal (miles USD/km)", fontsize=12)
    ax.set_title("Dispersión: CAPEX estimado vs. observado (líneas)\n"
                 "Modelo log-lineal (R²={:.3f}, MAPE={:.0f}%)".format(
                     m.score(X, y),
                     np.mean(np.abs(lineas["capex_obs_km"] - capex_pred_km/1000) /
                              lineas["capex_obs_km"]) * 100),
                 fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(True, which="both", alpha=0.3, linestyle="--")
    plt.tight_layout()
    out_fig2 = FIGS / "dispersion_observado.png"
    plt.savefig(out_fig2, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  ✓ Figura dispersión: {out_fig2}")
    print()

    # -----------------------------------------------------------------------
    # Resumen ejecutivo en texto
    # -----------------------------------------------------------------------
    resumen_txt = FIGS / "montecarlo_resumen.txt"
    with open(resumen_txt, "w") as f:
        f.write("=" * 78 + "\n")
        f.write("RESUMEN EJECUTIVO — Monte Carlo CAPEX & VATT\n")
        f.write(f"Fecha: 2026-07-20 | N simulaciones: {args.n:,} por escenario\n")
        f.write("=" * 78 + "\n\n")
        for r in resumen_rows:
            f.write(f"Escenario: {r['escenario']}\n")
            f.write(f"  CAPEX  P50: USD {r['capex_p50_usd']/1e6:,.2f} MM\n")
            f.write(f"  CAPEX  P75: USD {r['capex_p75_usd']/1e6:,.2f} MM\n")
            f.write(f"  CAPEX  P90: USD {r['capex_p90_usd']/1e6:,.2f} MM\n")
            f.write(f"  VATT   P50: USD {r['vatt_p50_usd']/1e6:,.3f} MM/año\n")
            f.write(f"  VATT   P90: USD {r['vatt_p90_usd']/1e6:,.3f} MM/año\n")
            f.write(f"  Banda P10-P90 VATT: ±{r['vatt_p10_p90_banda_pct']/2:.1f}% sobre P50\n\n")
    print(f"  ✓ Resumen TXT: {resumen_txt}")
    print()
    print("=" * 78)
    print("Listo. CSV + figuras + TXT en /workspace/modelador/")
    print("=" * 78)


if __name__ == "__main__":
    main()
