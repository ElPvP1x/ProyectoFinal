# Relatoría de etapa — E2

**Observatorio Contabilidad y Cumplimiento Fiscal** · Cristopher Amaro Granero y Yerik Monroy García

## 1. Qué se pidió

Integrar una fuente de datos especializada, hacer que cada registro de Oro sea rastreable hasta Bronce y su fecha de ingesta, y declarar la ética y legalidad del uso de los datos.

## 2. Qué se hizo

| Pieza | Archivo | Decisión principal |
|---|---|---|
| Extractor geoespacial | `src/extractor_geo.py` | DENUE (zip del INEGI, cada 90 días), Overpass (una consulta por corrida con reintentos) y geoBoundaries (una sola vez); todo corre en GitHub Actions |
| DENUE | `src/denue.py` | Lista blanca de columnas para no leer datos personales; validación cruzada de la entidad declarada |
| OSM y unión espacial | `src/geo.py` | Unión punto en polígono con respaldo por cercanía en la costa; cuarentena con motivo |
| Mapas | `docs/E2/mapa_despachos_denue.png`, `docs/E2/mapa_infraestructura.png` | Densidad de despachos (DENUE) y cobertura de OSM; bancos, SAT y recaudadoras |
| Linaje | `src/linaje.py`, `src/plata.py`, `src/oro.py` | Columnas de linaje en cada capa, tabla `linaje.csv` y verificación de hash contra el manifiesto |
| Ética | `docs/etica-datos.md` | Inventario de licencias, análisis de robots.txt, sesgos y privacidad |
| Pruebas | `tests/test_e2.py` | 9 pruebas nuevas; 18 en total |
| Automatización | `.github/workflows/captura.yml` | Paso de captura geoespacial que no detiene el flujo si una fuente falla |

## 3. Decisiones y su razón

1. **Geoespacial y no redes sociales.** Las métricas de YouTube o Mastodon sobre temas fiscales dicen poco del trabajo contable. La ubicación de despachos, oficinas del SAT y bancos sí se relaciona con él, y se puede trabajar sin datos personales.
2. **Dos fuentes en lugar de una.** Empezamos sólo con OpenStreetMap porque no pide token. Al ver que tenía 83 despachos en todo el país, buscamos una fuente oficial: la descarga masiva del DENUE tampoco pide token y tiene 16,936 establecimientos de contabilidad. OSM quedó para bancos, oficinas del SAT y recaudadoras, y la diferencia entre las dos fuentes se volvió un resultado (cobertura de OSM del 0.52 %).
3. **El DENUE se descarga en Actions, no a mano.** Así la captura queda con su fecha y su hash igual que las demás. Como el INEGI lo actualiza cada semestre, el extractor no lo vuelve a bajar si la captura tiene menos de 90 días.
4. **Lista blanca de columnas en el DENUE.** El archivo trae nombre, teléfono, correo y domicilio de personas físicas. En lugar de borrar esas columnas después, sólo se leen las necesarias: si el INEGI agrega una columna personal nueva, tampoco entra.
5. **Validar la entidad con la geometría.** El DENUE declara la entidad de cada establecimiento; compararla con la unión espacial mide la calidad de las coordenadas (99.99 % de concordancia) y detectó que geoBoundaries le pone a la Ciudad de México la clave del Estado de México.
6. **Separar SAT de recaudación local.** La etiqueta `government=tax` de OSM también la usan tesorerías estatales y municipales. El SAT se identifica por nombre.
7. **Densidad por área y no por población.** geoBoundaries no trae población y no se quiso meter una tabla copiada a mano sin linaje. Queda como mejora: cruzar con el Censo 2020 del INEGI.
8. **Linaje por archivo y no por cada valor.** Cada serie de Plata sale de un solo archivo de Bronce, así que basta con guardar archivo, hash y fecha de ingesta por fila, y en Oro, por mes. `linaje.csv` da el detalle y `src/linaje.py` recupera el texto crudo exacto.
9. **El hash detiene el pipeline.** Si un archivo de Bronce se editara a mano, Oro dejaría de corresponder a lo que publicó la fuente. Es preferible fallar a producir datos sin origen comprobable.
10. **robots.txt de Overpass.** Bloquea `/api/` para rastreadores. Se mantuvo la fuente porque el uso (una consulta semanal) cae dentro de su política de uso, y se documentó la alternativa.

## 4. Resultados

Con la prueba local del 23 de noviembre de 2026 (la captura oficial del DENUE la hace Actions):

- 16,936 establecimientos de contabilidad del DENUE en 992 municipios; 1,688 con 11 o más personas; 0 en cuarentena.
- Las 5 entidades con más despachos tienen el 32.1 % del total, contra el 48.6 % de los bancos. Guadalajara, Monterrey y Tijuana son los municipios con más despachos.
- OSM cubre el 0.52 % de los despachos del DENUE y en 16 entidades no tiene ninguno.
- 190 de 190 meses de Oro y 32 de 32 entidades con linaje completo.
- 18 de 18 pruebas pasan.

## 5. Defectos detectados durante la etapa

También están en `calidad/defectos-yerik.csv`.

| # | Defecto | Cómo se detectó | Corrección |
|---|---|---|---|
| 1 | Overpass respondió 502 (servidor saturado) en la primera captura | Prueba manual del extractor | Reintentos con espera creciente; el workflow sigue con la captura anterior |
| 2 | `government=tax` clasificaba recaudadoras municipales como oficinas del SAT | Revisión de los nombres de los elementos | Nueva categoría `recaudacion_local`; el SAT se identifica por nombre |
| 3 | La expresión regular del SAT perdió el `\b` al escribirse desde la terminal y dejó 12 oficinas en cuarentena | Cuarentena con `categoria_no_reconocida` | Se corrigió la expresión; cuarentena en 0 |
| 4 | El linaje mensual intentaba leer `geo_puntos.csv` como serie de tiempo | Error en el pipeline | Se excluyen los archivos `geo_*` |
| 5 | El verificador de 36 periodos fallaba con las carpetas geoespaciales | Revisión del flujo | Se omiten las fuentes que no son series de tiempo |
| 6 | El mapa perdía la leyenda de la escala de color | Revisión de la imagen | Se conservan las dos leyendas |
| 7 | Git iba a convertir los fines de línea de los JSON de Bronce en Windows y el hash dejaría de coincidir | Aviso de Git al hacer commit | `.gitattributes` con `-text` para las capturas; prueba en un clon nuevo |
| 8 | OSM sólo tenía 83 despachos: la fuente no servía para medir el sector | Revisión de resultados | Se agregó el DENUE |
| 9 | La columna `entidad` del DENUE chocaba con la que agrega la unión espacial | Revisión del código | Se renombra a `entidad_denue` antes de la unión |
| 10 | geoBoundaries asigna `MX-MEX` a la Ciudad de México | Validación cruzada contra el DENUE | Se corrige a `MX-CMX` al leer los polígonos |
| 11 | En el mapa de cobertura, las entidades en 0 % salían blancas sin borde | Revisión de la imagen | Borde gris |

## 6. Reflexión

**Lo que funcionó.** Guardar Bronce crudo con hash desde E0 hizo que el linaje fuera casi gratis: bastó con arrastrar archivo, hash y fecha de ingesta por las capas. La validación cruzada entre dos fuentes encontró un error en una tercera (la clave de la Ciudad de México en geoBoundaries) que con una sola fuente no habríamos visto.

**Lo que cambiaríamos.** Elegimos OSM por comodidad (no pide token) antes de medir su cobertura. Debimos comparar contra una fuente oficial desde el principio: el criterio para escoger una fuente debe ser qué tan bien representa al sector, no qué tan fácil es de consultar. También conviene escribir las expresiones regulares en archivos y no desde la terminal, donde los escapes se pierden.

**Lo que aprendimos.** Que un dato sea público no quiere decir que se pueda usar de cualquier forma: el DENUE es abierto, pero trae datos de personas físicas y hay que decidir qué columnas se leen antes de abrir el archivo. Y que robots.txt y la política de uso de un servicio dicen cosas distintas: hay que leer los dos.

## 7. Pendiente

- Cristopher: registrar sus tiempos y defectos de E2 en `calidad/tiempo-cristopher.csv` y `calidad/defectos-cristopher.csv`.
- Anotar en `docs/E2/ENTREGA.md` el enlace a la corrida de Actions que descargue el DENUE.
- Mejora: población por entidad y municipio (Censo 2020) para densidad per cápita.
