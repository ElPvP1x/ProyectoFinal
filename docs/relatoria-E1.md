# Relatoría de etapa — E1

**Observatorio Contabilidad y Cumplimiento Fiscal** · Cristopher Amaro Granero y Yerik Monroy García

> Borrador técnico. Las secciones 5 y 6 (tiempos, defectos y reflexión del equipo) las completan los integrantes con sus propios registros PSP; aquí no se inventan.

## 1. Qué se pidió

Automatizar el paso de Bronce a Plata y Oro con limpieza estadística y una puerta de calidad que mande a cuarentena, con motivo, los registros inválidos.

## 2. Qué se hizo

| Pieza | Archivo | Decisión principal |
|---|---|---|
| Puerta de calidad | `src/calidad.py` | Esquema estricto con Pandera; un registro inválido va a cuarentena con su motivo, un esquema roto detiene todo el lote |
| Limpieza | `src/limpieza.py`, `src/plata.py` | Diagnóstico de faltantes, imputación elegida por error de validación, atípicos marcados y no borrados |
| Integración y reducción | `src/oro.py` | Rejilla mensual común, selección por redundancia (|r| > 0.95), normalización y discretización |
| Orquestación | `src/pipeline.py` | Falla si la cuarentena pasa de 5 % o hay menos de 36 meses completos |
| Automatización | `.github/workflows/captura.yml` | Después de capturar, ejecuta pipeline y pruebas; guarda Plata, Oro y cuarentena en el repo |
| Evidencia | `docs/E1/limpieza.ipynb`, `tests/test_pipeline.py` | Cuaderno ejecutado y 9 pruebas |

## 3. Decisiones y su razón

1. **Faltantes = MAR, no MCAR.** FIX y TIIE no publican en feriados bancarios. La ausencia depende del mes (χ², p ≈ 5×10⁻¹⁸) pero no del nivel previo (p ≈ 0.77 a 0.78) ni, de forma significativa, de la volatilidad previa (p ≈ 0.08 a 0.10). MNAR se descarta por origen, no por prueba.
2. **Interpolación lineal.** Con el 5 % de valores conocidos ocultos, tuvo el menor error: MAE 0.065 contra 0.088 del último valor en FIX, y 0.009 contra 0.015 en TIIE. La media global fue mucho peor (MAE > 2).
3. **Los atípicos se marcan, no se borran.** Los más fuertes del FIX coinciden con eventos (9-nov-2016, marzo de 2020, 7-jun-2024). Borrarlos sería quitar información real. Se ofrece `variacion_winsor` para modelado.
4. **UDIS fuera de la tabla final.** Su valor se calcula a partir del INPC (|r| ≈ 1), así que repetirla no agrega información.
5. **Meses parciales marcados, no eliminados.** Los primeros 12 meses no tienen inflación anual y el mes en curso no tiene INPC.
6. **Series escalonadas.** En la TIIE, el IQR y el MAD de las variaciones pueden ser cero; los detectores se calibran con las variaciones distintas de cero para no marcar cada cambio.

## 4. Resultados

Con la captura del 16 de noviembre de 2026: 14,852 registros de Bronce, todos válidos y 0 en cuarentena. Quedan 203 meses en Oro, 190 completos. Las 9 pruebas pasan. Los seis defectos del lote de prueba llegan a cuarentena con su motivo.

La cuarentena real quedó vacía, así que la prueba de que funciona es el lote sintético, no un caso real. Cuando Banxico o INEGI entreguen un dato defectuoso, aparecerá en `datos/cuarentena/cuarentena.csv`.

## 5. Defectos detectados durante la etapa

Estos defectos se encontraron y corrigieron al construir el pipeline. Hay que registrarlos en `calidad/defectos-*.csv` con la fase y los minutos de corrección de quien los atendió.

| # | Defecto | Cómo se detectó | Corrección |
|---|---|---|---|
| 1 | La puerta repetía el mismo rechazo una vez por columna | Prueba con lote de defectos | Un motivo por registro y por regla |
| 2 | El motivo salía vacío en algunos rechazos | Prueba con lote de defectos | Construcción explícita del texto del motivo |
| 3 | Un valor ausente (`N/E`) producía además un falso rechazo por rango | Prueba con lote de defectos | La regla de rango ignora los ausentes |
| 4 | La TIIE marcaba cientos de atípicos falsos | Revisión de los conteos | Calibración sobre variaciones distintas de cero |
| 5 | La tabla Oro traía la columna `mes` duplicada | Revisión del CSV | Se quita la copia de la jerarquía |

## 6. Pendiente del equipo

- Registrar tiempos (`calidad/tiempo-*.csv`) y defectos (`calidad/defectos-*.csv`) reales de E1.
- Reflexión: qué aprendió cada integrante y qué haría distinto.
- Realizar la entrevista de campo de E0, que sigue pendiente, y revisar si cambia alguna decisión de esta etapa.
- Crear el secreto `INEGI_TOKEN` y confirmar el indicador, para integrar la segunda fuente.
- Correr el workflow en Actions y anotar el enlace en `docs/E1/ENTREGA.md`.
