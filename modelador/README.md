# Modelo de estimación de CAPEX y VATT — Transmisión Chile (Ley 20.936)

Reproduce la cadena: dataset → regresión paramétrica → simulación Monte Carlo → distribución del VATT anualizado.

## Requisitos

- Python 3.10+
- numpy, pandas, scikit-learn ≥1.0, matplotlib, scipy

```bash
pip install --break-system-packages numpy pandas scikit-learn matplotlib scipy
```

## Cómo ejecutar (en orden)

```bash
# 1) Regresión paramétrica + figura CAPEX vs tensión
python regression.py

# 2) Monte Carlo: 5 escenarios por defecto + figuras
python montecarlo.py

# 3) (Opcional) Figura VATT individual
python extra_fig_vatt.py
```

Para correr un escenario personalizado:

```bash
python montecarlo.py --custom --kv 220 --ctos 1 --km 100 --terreno rural --n 10000
```

## Archivos generados

| Archivo | Descripción |
|---|---|
| `dataset.csv` | Dataset consolidado (líneas + S/E) extraído de CNE, World Bank, ACER, Coordinadores |
| `regression.py` | Modelo log-lineal y lineal para CAPEX/km; exporta coeficientes y R²/MAPE |
| `montecarlo.py` | Simulador Monte Carlo (N configurable) con perturbaciones en costo, terreno, longitud, contingencias, tasa, vida útil, COMA |
| `reportable.csv` | Tabla con P10/P50/P75/P90 de CAPEX y VATT por escenario |
| `figs/capex_vs_tension.png` | Dispersión de CAPEX unitario vs tensión con curva log-lineal ajustada |
| `figs/dispersion_observado.png` | Estimado vs observado con banda ±25% |
| `figs/montecarlo_capex.png` | Histograma de CAPEX (P50/P75/P90 marcados) |
| `figs/montecarlo_vatt.png` | Histograma de VATT (P50/P75/P90 marcados) |
| `figs/regression_summary.json` | Coeficientes y métricas de regresión (consumible por downstream) |
| `figs/montecarlo_resumen.txt` | Resumen ejecutivo en texto plano |

## Supuestos clave (defaults)

| Parámetro | Valor | Fuente / Justificación |
|---|---|---|
| Tasa de descuento | 6% real (rango 6-10% en MC) | Res. Exenta CNE vigente 2020-2023 |
| Vida útil línea | 30 años | SII + estándar CNE |
| Vida útil S/E | 25 años | SII + estándar CNE |
| COMA | 1.5-3.5% del AVI (uniforme) | Rango histórico procesos CNE |
| CV costo unitario | 22% (lognormal) | Calibrado con dispersión World Bank 2026 + ITP CNE 2022 |
| Variabilidad longitud | ±20% triangular | Estándar de proyectos de transmisión |
| Contingencias | PERT (1.0 / 1.12 / 1.45) | Recomendación CIGRE 2017 + práctica CNE |
| Semilla aleatoria | 20260720 (fija) | Reproducibilidad |

## Supuestos y limitaciones (importante)

- El dataset combina datos **de Chile** (CNE, Coordinador) con **benchmarks
  internacionales** (World Bank 2026, ACER 2023, NCEP 2003) calibrados a CLP/USD
  del período. Para mayor precisión se recomienda restringir la regresión solo a
  obras chilenas (≥30 obras adicionales) — el modelo degrada a R²≈0.55 si se hace
  esa restricción.
- Los costos de subestaciones son **orientativos** (n=8 en la muestra);
  recomiendo recabar ≥30 licitaciones chilenas para refinar.
- La fórmula del VATT usa la **Resolución CNE vigente**. Cambios
  regulatorios (ej. nueva tasa, vida útil) requieren recalibrar.
- El HVDC está representado con un solo proyecto ancla (Kimal-Lo Aguirre
  adjudicado 2026), por lo que el error relativo es mayor.
