# Ficha de entrega técnica — E1

| Campo | Valor |
|---|---|
| Equipo / integrantes | Cristopher Amaro Granero, Yerik Monroy García |
| Repositorio | https://github.com/ElPvP1x/ProyectoFinal |
| Tag | `e1` |
| Sector | Contabilidad y cumplimiento fiscal (Sistema Contable, Auditor de CFDI 4.0) |
| Profesores agregados como colaboradores | [usuario 1], [usuario 2], [usuario 3] |

## Entregables

| Entregable | Ubicación | Estado |
|---|---|---|
| Pipeline de limpieza y preprocesamiento (cuaderno) | `docs/E1/limpieza.ipynb` | [x] ejecutado, con salidas y gráficas |
| Pipeline de limpieza y preprocesamiento (scripts) | `src/limpieza.py`, `src/plata.py`, `src/oro.py`, `src/pipeline.py` | [x] |
| Valores faltantes: mecanismo e imputación | cuaderno, sección 2 · `datos/plata/reporte.json` | [x] MAR, interpolación lineal elegida por error mínimo |
| Atípicos y ruido (IQR, Z robusto, Isolation Forest) | cuaderno, sección 3 · columnas `atipico_*` en `datos/plata/*.csv` | [x] se marcan, no se eliminan |
| Normalización Min-Max y Z-Score | cuaderno, sección 6 · columnas `*_mm` y `*_z` en `datos/oro/oro_mensual.csv` | [x] |
| Discretización y jerarquías conceptuales | cuaderno, sección 7 · `fix_nivel`, `tiie_nivel`, `inflacion_nivel`, `trimestre`, `semestre`, `anio` | [x] |
| Reducción de datos (agregación y selección de variables) | cuaderno, sección 5 · `datos/oro/reporte.json` | [x] |
| Integración de fuentes heterogéneas | `src/plata.py` (`leer_bronce`) y `src/oro.py` (`integrar`) · cuaderno, sección 4 | [x] Banxico; INEGI listo pero sin captura (falta `INEGI_TOKEN`) |
| Puerta de calidad (Pandera) y cuarentena | `src/calidad.py` · `datos/cuarentena/cuarentena.csv` | [x] |
| Pruebas automáticas | `tests/test_pipeline.py` | [x] 9 pruebas |
| Automatización | `.github/workflows/captura.yml` | [ ] falta correrlo en Actions con el pipeline nuevo y anotar el enlace |
| Relatoría de etapa | `docs/relatoria-E1.md` | [x] borrador; los tiempos y defectos del PSP los registra el equipo |

## Resultados con los datos de Bronce de la captura del 2026-11-16

| Medida | Valor |
|---|---|
| Registros de Bronce leídos | 14,852 (4 series de Banxico) |
| Válidos / en cuarentena | 14,852 / 0 (0 %) |
| Días hábiles sin dato en FIX y TIIE | 157 de 4,400 (3.6 %), imputados por interpolación lineal y marcados en `imputado` |
| Meses en la tabla Oro | 203 (190 completos; 13 parciales, marcados en `mes_completo`) |
| Variables conservadas | `fix_prom`, `tiie_prom`, `inpc`, `inflacion_anual`, `fix_std`, `fix_var_mensual`, `tasa_real` |
| Variables descartadas por redundancia | `fix_cierre`, `tiie_cierre`, `udis_prom`, `udis_cierre` (|r| > 0.99) |

Con los datos reales de Banxico no hubo registros rechazados. Para demostrar la cuarentena hay un lote de prueba con seis defectos
(`tests/test_pipeline.py` y sección 1 del cuaderno): los seis llegan a cuarentena con su motivo y ninguno se pierde.

## Capas de datos

| Capa | Carpeta | Contenido |
|---|---|---|
| Bronce | `datos/bronce/` | respuesta cruda de la API, con fecha y hash (sin cambios desde E0) |
| Cuarentena | `datos/cuarentena/cuarentena.csv` | registros inválidos con la columna `motivo` |
| Plata | `datos/plata/<serie>.csv` | serie validada, calendario completo, `imputado`, `valor_limpio`, variaciones y banderas de atípicos |
| Oro | `datos/oro/oro_mensual.csv` | tabla mensual reducida, normalizada y discretizada, lista para E1, E2 y E3 |
| Oro (integrada) | `datos/oro/integrado_mensual.csv` | todas las variables mensuales antes de reducir |

## 3 objetivos de calidad medibles

1. **Cuarentena ≤ 5 %** de los registros de Bronce. El pipeline termina con error si se supera (`MAX_PCT_CUARENTENA` en `src/pipeline.py`). Resultado actual: 0 %.
2. **Cero registros perdidos en silencio:** válidos + cuarentena = registros de entrada. Lo verifica `test_nada_se_pierde_en_silencio`.
3. **Pruebas al 100 %:** las 9 pruebas de `tests/` pasan en cada corrida del workflow. Resultado actual: 9 de 9.

## Cómo reproducir

```
pip install -r requirements.txt
python src/pipeline.py
python -m pytest -q tests
```

El cuaderno se abre desde `docs/E1/limpieza.ipynb`. Las capturas de Bronce se generan con `BANXICO_TOKEN=... python src/extractor.py`.

## Diccionario de `datos/oro/oro_mensual.csv`

| Columna | Descripción |
|---|---|
| `mes`, `anio`, `semestre`, `trimestre` | jerarquía temporal |
| `fix_prom`, `fix_std` | media y desviación mensual del tipo de cambio FIX (MXN por USD) |
| `fix_var_mensual` | variación porcentual mensual del promedio del FIX |
| `tiie_prom` | media mensual de la TIIE a 28 días (%) |
| `inpc` | índice nacional de precios al consumidor |
| `inflacion_anual` | variación porcentual del INPC frente al mismo mes del año anterior |
| `tasa_real` | `tiie_prom` menos `inflacion_anual` |
| `<variable>_mm`, `<variable>_z` | versión Min-Max y Z-Score |
| `fix_nivel`, `tiie_nivel`, `inflacion_nivel` | variables discretizadas |
