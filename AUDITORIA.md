# Auditoría de código — CAPEX y Peajes de Transmisión

**Fecha:** 2026-09-30 · **Alcance:** `modelador/regression.py`, `modelador/montecarlo.py`, `modelador/extra_fig_vatt.py`, `modelador/dataset.csv`, `modelador/reportable.csv`, entregables de tracks e informe final.

**Entregable asociado:** `dashboard/index.html` — dashboard interactivo D3.js que reimplementa la regresión y el Monte Carlo en vivo. Los números del dashboard cuadran con el modelo Python (η=1,76 · R²=0,69 · premio 2º circuito +10,6% · MAPE 79,2% · MC P50 línea 2×500: 342,6 vs 344,2 MM USD; S/E GIS 57,6 vs 57,1 MM — paridad < 1,5%).

---

## A · Bugs y errores metodológicos (prioridad alta)

1. **Curva del gráfico mal etiquetada (`regression.py:179-188`).** Las columnas del modelo son `[log_tension, log_circuitos, d_urbano, d_rural, d_cordillera]` (TERRENOS = urbano, rural, cordillera), pero `X_curve` pone el vector de `ones` en la posición 2 comentada como `# rural`. Resultado: la curva dibujada como “1 cto, rural” es en realidad la **urbana** (~1,7× más alta que la rural, exp(0,535)). El PNG `capex_vs_tension.png` hereda el error.

2. **Trampa de dummies (`regression.py:65`).** El intercepto + las 3 dummies de terreno son colineales (suma de dummies = 1). `LinearRegression` resuelve por mínima norma (los β de terreno suman 0), así que predicciones y R² son correctos, pero los coeficientes **no son interpretables como premios**: “urbano +0,53” no significa +71% vs rural; con base rural el efecto real sería +164% (exp(0,97)−1, n urbano = 2). Recomendado: drop `d_rural` y documentar la base.

3. **Comparación de modelos inválida (`regression.py:137`).** `best = "log-lineal" if r2_log >= r2_lin` compara un R² calculado **en log** contra uno calculado **en nivel**: no son comparables. Además deja `modelo_recomendado: "lineal"` en `regression_summary.json`, mientras el informe final y el dashboard usan el log-lineal. Unificar criterio (p. ej. MAPE en nivel o R² en nivel para ambos).

4. **Regresión duplicada con riesgo de drift (`montecarlo.py:383-394`).** El gráfico de dispersión reentrena su propia regresión en vez de leer `figs/regression_summary.json`. Si alguien recalibra `regression.py`, el reportable y sus figuras quedan desacoplados. Leer el JSON.

5. **MAPE por re-transformación sin corrección (`regression.py:75`).** `exp(pred)` es la mediana, no la media (sesgo de re-transformación lognormal); sin factor de Duan/smearing el MAPE en nivel está sesgado. Documentar o corregir.

6. **`warnings.filterwarnings("ignore")` global (`regression.py:33`).** Oculta problemas de convergencia/dtype. Mejor filtrar por categoría.

## B · Calidad de datos (`dataset.csv`)

7. **L04**: `tipo=linea` con `longitud_km=0` y CAPEX 106 MM — se excluye sola de la regresión, pero conviene aclarar el alcance (parece obra sin desglose de línea).
8. **L13 y L14** (8.475 y 13.231 USD/km, obras adjudicadas 2021) están 1–2 órdenes de magnitud bajo el resto de la muestra (~100 k–1,2 M USD/km): distinto alcance (zonal/distribución). Arrastran el intercepto; agregar flag de exclusión o columna “alcance”.
9. **Años 2009–2026 sin deflactar** y alcances mezclados (línea pura vs proyecto total — p. ej. HVDC1 ~1.100 MUSD/km todo el proyecto vs 784 línea pura). El README lo reconoce, pero conviene columna `alcance` + deflactor para la v2.
10. **`com_a_pct` constante 2,5%** en las 36 filas (columna sin información) y **contradice** el 1,6% estándar CNE que documenta `track-costos-unitarios` (1,79% Plan 2024).

## C · Inconsistencias documentales

11. **Tasa regulatoria:** `montecarlo.py` usa 6% (uniforme 6–10%), el README dice “6% real vigente”, el informe dice 6%, pero `track-costos-unitarios` documenta **7% real vigente** (ITD 2020-2023, mantenido 2024-2026). Unificar en 7% o justificar el rango.
12. **Nombres de figuras:** `montecarlo.py` escribe `montecarlo_resultados.png`, pero el README lista `montecarlo_capex.png`/`montecarlo_vatt.png` (este último sale de `extra_fig_vatt.py`). Actualizar README.
13. **Ruta hardcodeada** en el mensaje final de `regression.py` (“/workspace/modelador/figs/”) — usar `FIGS.resolve()`.
14. **`extra_fig_vatt.py` duplica** la lógica del histograma de `montecarlo.py`; `informe-final/figs` duplica las imágenes de `modelador/figs`.
15. **Reproducibilidad:** la semilla global `RNG` + seed CLI funciona en el flujo actual, pero `simular_obra()` sin `seed` depende del orden de llamadas; documentar o exigir seed.
16. **“R²≈0,55 solo Chile” (README)** no se reproduce con la especificación actual: el log-lineal con n=19 chilenas da R²(log) ≈ 0,73 (verificado en el dashboard, toggle “Solo Chile”). Verificar el origen de esa cifra o corregirla.

## D · Lo que está bien (mantener)

- Semillas fijas y salidas machine-readable (`regression_summary.json`, `reportable.csv`).
- Implementaciones correctas de lognormal-CV, triangular, Beta-PERT y la anualidad regulatoria.
- Supuestos documentados con fuente, bandas P10–P90 y validación contra la adjudicación real del HVDC Kimal–Lo Aguirre.
- Separación clara dataset → regresión → simulación → reportable.

## E · Recomendaciones v2 (orden sugerido)

1. Corregir curva mal etiquetada + trampa de dummies + criterio de selección de modelo (A1–A3).
2. Limpieza de dataset: flag `alcance`, `chile/benchmark`, deflactor, revisar L04/L13/L14 (B7–B9).
3. `montecarlo.py` que lea `regression_summary.json` (A4) y tasa 7% con sensibilidad 5/7/10 (C11).
4. Regenerar figuras + informe y re-chequear los números citados (η, premios, R² Chile-only).
