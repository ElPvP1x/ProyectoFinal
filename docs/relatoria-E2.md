# Relatoría de etapa — E2

**Observatorio Contabilidad y Cumplimiento Fiscal** · Cristopher Amaro Granero y Yerik Monroy García

> Borrador técnico. Las secciones 5 y 6 (tiempos, defectos y reflexión del equipo) las completan los integrantes con sus propios registros PSP; aquí no se inventan.

## 1. Qué se pidió

Integrar una fuente de datos especializada, hacer que cada registro de Oro sea rastreable hasta Bronce y su fecha de ingesta, y declarar la ética y legalidad del uso de los datos.

## 2. Qué se hizo

| Pieza | Archivo | Decisión principal |
|---|---|---|
| Extractor geoespacial | `src/extractor_geo.py` | Una consulta a Overpass por corrida, con reintentos de 30 a 240 s; los polígonos sólo se bajan si no hay captura |
| Procesamiento geoespacial | `src/geo.py` | Sólo campos no personales; cuarentena con motivo; unión punto en polígono y respaldo por cercanía en la costa |
| Mapa | `docs/E2/mapa_infraestructura.png` | Coropleta de densidad de bancos en quintiles y puntos para despachos, SAT y recaudadoras |
| Linaje | `src/linaje.py`, `src/plata.py`, `src/oro.py` | Columnas de linaje en cada capa, tabla `linaje.csv` y verificación de hash contra el manifiesto |
| Ética | `docs/etica-datos.md` | Inventario de licencias, análisis de robots.txt, sesgos y privacidad |
| Pruebas | `tests/test_e2.py` | 7 pruebas nuevas; 16 en total |
| Automatización | `.github/workflows/captura.yml` | Paso de captura geoespacial que no detiene el flujo si Overpass está saturado |

## 3. Decisiones y su razón

1. **Geoespacial y no redes sociales.** Las métricas de YouTube o Mastodon sobre temas fiscales dicen poco del trabajo contable. La ubicación de oficinas del SAT, recaudadoras y bancos sí se relaciona con él, y además no exige datos personales.
2. **OpenStreetMap en lugar del DENUE.** El DENUE es la fuente oficial y mucho más completa, pero requiere token y el equipo no lo tiene todavía (igual que el `INEGI_TOKEN`). OSM no requiere token y tiene licencia abierta. El costo es una cobertura muy baja de despachos contables, que se documenta como sesgo.
3. **Separar SAT de recaudación local.** La etiqueta `government=tax` también la usan tesorerías y recaudadoras estatales y municipales. Clasificarlas todas como SAT inflaba la cifra federal, así que el SAT se identifica por nombre.
4. **Bancos como capa principal del mapa.** Con 5,025 elementos es la única categoría con cobertura suficiente para comparar entidades. Los despachos van como puntos, sin rellenar la coropleta, para no sugerir una precisión que no tienen.
5. **Densidad por área y no por población.** geoBoundaries no trae población y no se quiso meter una tabla de población copiada a mano sin linaje. Queda como mejora: cruzar con el Censo 2020 del INEGI.
6. **Linaje por archivo y no por cada valor.** Cada serie de Plata sale de un solo archivo de Bronce, así que basta con guardar archivo, hash y fecha de ingesta por fila, y en Oro, por mes. `linaje.csv` da el detalle por mes y serie, y `src/linaje.py` recupera el texto crudo exacto.
7. **El hash detiene el pipeline.** Si un archivo de Bronce se editara a mano, Oro dejaría de corresponder a lo que publicó la fuente. Es preferible fallar a producir datos sin origen comprobable.
8. **robots.txt de Overpass.** Bloquea `/api/` para rastreadores. Se decidió mantener la fuente porque el uso (una consulta semanal) cae dentro de su política de uso, y se dejó documentada la alternativa (extracto de Geofabrik o DENUE) si el uso creciera.

## 4. Resultados

- 5,234 elementos de OSM, todos válidos; 7 asignados por cercanía en la costa.
- El 48.6 % de los bancos registrados está en 5 entidades; la Ciudad de México tiene casi 500 bancos por 1,000 km².
- 5 entidades (Campeche, Chiapas, Durango, Guerrero y Sinaloa) no tienen ningún despacho, oficina del SAT ni recaudadora registrados en OSM, lo que confirma el sesgo de cobertura.
- 190 de 190 meses de Oro y 32 de 32 entidades con linaje completo; 811 filas en `linaje.csv`.
- 16 de 16 pruebas pasan.

## 5. Defectos detectados durante la etapa

Hay que registrarlos en `calidad/defectos-*.csv` con la fase y los minutos de corrección de quien los atendió.

| # | Defecto | Cómo se detectó | Corrección |
|---|---|---|---|
| 1 | Overpass respondió 502 (servidor saturado) en la primera captura | Prueba manual del extractor | Reintentos con espera creciente; el workflow sigue con la captura anterior |
| 2 | `government=tax` clasificaba recaudadoras municipales como oficinas del SAT | Revisión de los nombres de los elementos | Nueva categoría `recaudacion_local`; el SAT se identifica por nombre |
| 3 | La expresión regular del SAT perdió el `\b` al escribirse desde la terminal y dejó 12 oficinas en cuarentena | Cuarentena con `categoria_no_reconocida` | Se corrigió la expresión; cuarentena en 0 |
| 4 | El linaje mensual intentaba leer `geo_puntos.csv` como serie de tiempo | Error en el pipeline | Se excluyen los archivos `geo_*` |
| 5 | El verificador de 36 periodos fallaba con las carpetas geoespaciales | Revisión del flujo | Se omiten las fuentes que no son series de tiempo |
| 6 | El mapa perdía la leyenda de la escala de color | Revisión de la imagen | Se conservan las dos leyendas |

## 6. Pendiente del equipo

- Registrar tiempos (`calidad/tiempo-*.csv`) y defectos (`calidad/defectos-*.csv`) reales de E2.
- Reflexión: qué aprendió cada integrante y qué haría distinto.
- Correr el workflow en Actions y anotar el enlace en `docs/E2/ENTREGA.md`.
- Solicitar el token del INEGI para comparar con el DENUE y para integrar el INPC del BIE.
