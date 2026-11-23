# Ficha de entrega técnica — E2

| Campo | Valor |
|---|---|
| Equipo / integrantes | Cristopher Amaro Granero, Yerik Monroy García |
| Repositorio | https://github.com/ElPvP1x/ProyectoFinal |
| Tag | `e2` |
| Sector | Contabilidad y cumplimiento fiscal (Sistema Contable, Auditor de CFDI 4.0) |
| Fuente especializada elegida | **Geoespacial:** OpenStreetMap (Overpass API) + polígonos de entidades de geoBoundaries / INEGI, con GeoPandas |

## Entregables

| Entregable | Ubicación | Estado |
|---|---|---|
| Fuente especializada: extractor | `src/extractor_geo.py` · configuración en `config/fuentes.yml` (`osm_overpass`, `geoboundaries`) | [x] |
| Fuente especializada: Bronce crudo | `datos/bronce/osm_overpass/…/20261123T144742Z.json`, `datos/bronce/geoboundaries/…/20261123T144743Z.json` | [x] con hash en `manifiesto.csv` |
| Procesamiento con GeoPandas (unión espacial punto en polígono) | `src/geo.py` | [x] |
| Visualización cartográfica | `docs/E2/mapa_infraestructura.png` | [x] |
| Plata y Oro geoespaciales | `datos/plata/geo_puntos.csv`, `datos/oro/geo_entidades.csv`, `datos/cuarentena/geo_cuarentena.csv` | [x] |
| Declaración de ética y legalidad | `docs/etica-datos.md` | [x] términos, robots.txt, licencias, sesgos y privacidad |
| Linaje y trazabilidad | `src/linaje.py` · `datos/oro/linaje.csv` · columnas de linaje en Plata y Oro | [x] |
| Pruebas | `tests/test_e2.py` (7 nuevas) + `tests/test_pipeline.py` (9 de E1) | [x] 16 de 16 pasan |
| Automatización | `.github/workflows/captura.yml`: captura geoespacial, pipeline y pruebas cada lunes | [ ] falta correrlo en Actions y anotar el enlace |
| Relatoría de etapa | `docs/relatoria-E2.md` | [x] borrador; tiempos y defectos PSP los registra el equipo |

## 1. Fuente especializada: geoespacial

**Pregunta:** ¿dónde está la infraestructura que usa un contador (despachos, oficinas del SAT, recaudadoras y bancos) y qué tan desigual es su distribución entre entidades?

| Paso | Detalle |
|---|---|
| Puntos | Una consulta a Overpass por corrida: `office=accountant`, `office=tax_advisor`, `government=tax`, nombre "SAT" o "Servicio de Administración Tributaria", y `amenity=bank` |
| Polígonos | geoBoundaries gbOpen MEX ADM1 (32 entidades, simplificado, derivado del Marco Geoestadístico del INEGI) |
| Calidad | Categoría reconocida, coordenadas presentes, dentro de México, sin duplicados; lo que falla va a `geo_cuarentena.csv` con motivo |
| Unión espacial | `gpd.sjoin(puntos, entidades, predicate="within")`; los puntos costeros que caen fuera del polígono simplificado se asignan a la entidad más cercana (≤ 5 km) con `sjoin_nearest` y se marcan |
| Métricas por entidad | conteo por categoría, área en km² (EPSG:6372), bancos por 1,000 km², % nacional de bancos |

**Resultados de la captura del 23 de noviembre de 2026**

| Medida | Valor |
|---|---|
| Elementos de OSM en Bronce | 5,234 |
| Válidos / cuarentena | 5,234 / 0 |
| Por categoría | 5,025 bancos · 83 despachos contables · 63 oficinas del SAT · 58 recaudadoras estatales o municipales · 5 asesores fiscales |
| Asignación espacial | 5,227 dentro del polígono · 7 a la entidad más cercana (costa) |
| Concentración | 5 entidades (CDMX, Jalisco, Nuevo León, Estado de México y Veracruz) concentran el 48.6 % de los bancos registrados |
| Densidad | Ciudad de México: 497.9 bancos por 1,000 km²; la mediana de las 32 entidades es 2.5 |
| Huecos de cobertura | 5 entidades sin ningún despacho, oficina del SAT o recaudadora registrada en OSM: Campeche, Chiapas, Durango, Guerrero y Sinaloa |

Los 83 despachos contables de OSM son una fracción mínima de los reales. Ese hueco es un hallazgo sobre la fuente, no sobre el sector, y se discute en `docs/etica-datos.md` (sección 3). La comparación natural es el DENUE del INEGI (SCIAN 541211, servicios de contabilidad y auditoría), que requiere token.

## 2. Linaje y trazabilidad

Cada registro de Oro se rastrea hasta su archivo de Bronce y su fecha de ingesta.

| Capa | Qué lleva cada registro |
|---|---|
| Bronce | archivo `<captura>.json` + fila en `manifiesto.csv` con bytes y SHA-256 |
| Plata (series) | `origen` (`bronce` o `imputado (interpolacion)`), `fecha_ingesta`, `archivo_bronce`, `sha256_bronce` |
| Plata (geo) | igual, por cada punto, más `osm_tipo` y `osm_id` para ubicar el elemento original |
| Oro mensual | `fecha_ingesta`, `archivos_bronce` (todos los archivos que formaron el mes), `registros_bronce` |
| Oro geo | `archivo_bronce_puntos`, `archivo_bronce_entidades`, sus hashes y `fecha_ingesta` |
| Detalle | `datos/oro/linaje.csv`: 811 filas, una por (mes, serie), con registros de Bronce aportados, imputados y rango de fechas |

**Verificación de integridad.** Antes de usar un archivo de Bronce se recalcula su SHA-256 y se compara con el manifiesto. Si no coincide o el archivo no está registrado, el pipeline se detiene (`linaje.ficha_archivo`).

**Rastrear un mes:**

```
python src/linaje.py 2024-06
Mes 2024-06: 71 registros crudos de Bronce
inpc_general_mensual  <-  datos/bronce/banxico_sie/inpc_general_mensual/20261116T231052Z.json  (ingesta 2026-11-16T23:10:52Z, 1 registros)
tiie_28_dias_diaria   <-  datos/bronce/banxico_sie/tiie_28_dias_diaria/20261116T231054Z.json   (ingesta 2026-11-16T23:10:54Z, 20 registros)
...
```

Variables derivadas: `inflacion_anual` usa el INPC del mes y del mismo mes del año anterior, y `fix_var_mensual` usa el mes anterior. Esos meses también están en `linaje.csv`, con el mismo archivo de Bronce.

## 3. Ética y legalidad

Resumen de `docs/etica-datos.md`:

- **Licencias:** Banxico (citar fuente), INEGI (términos de libre uso), OSM (ODbL 1.0), geoBoundaries (CC BY 3.0 IGO). La atribución va en el mapa.
- **robots.txt:** las rutas de API de Banxico, INEGI y geoBoundaries están permitidas. Overpass bloquea `/api/` para rastreadores; nuestro uso es una consulta semanal dentro de su política de uso, con User-Agent propio y espera creciente al recibir 429 o 5xx.
- **Privacidad:** de OSM sólo se conservan id, tipo, categoría y coordenadas; nombres y teléfonos se descartan (prueba automática). Oro está agregado por entidad.
- **Sesgos:** cobertura desigual de OSM, tamaño de las entidades, etiquetado inconsistente y polígonos simplificados, cada uno con su mitigación.

## 4. Objetivos de calidad medibles (E2)

1. **100 % de los registros de Oro con linaje completo:** `test_cada_registro_de_oro_es_rastreable`. Resultado: 190 de 190 meses y 32 de 32 entidades.
2. **Cero datos personales en Plata y Oro geoespaciales:** `test_geo_descarta_datos_personales_y_manda_a_cuarentena`. Resultado: ninguna columna de nombre, teléfono o dirección.
3. **Integridad de Bronce:** todo archivo usado coincide con su hash del manifiesto; el pipeline se detiene si no. Resultado: 6 de 6 archivos verificados.

## Cómo reproducir

```
pip install -r requirements.txt
python src/extractor_geo.py        # captura OSM y geoBoundaries (sin token)
python src/pipeline.py             # Bronce -> Plata -> Oro (series y geo) + mapa
python -m pytest -q tests
python src/linaje.py 2024-06       # rastrea un mes de Oro hasta Bronce
```

## Diccionario de `datos/oro/geo_entidades.csv`

| Columna | Descripción |
|---|---|
| `entidad`, `clave_iso` | nombre y clave ISO 3166-2 de la entidad |
| `area_km2` | área calculada en EPSG:6372 |
| `despacho_contable`, `asesor_fiscal`, `oficina_sat`, `recaudacion_local`, `banco` | conteo de elementos de OSM por categoría |
| `total`, `contables_y_fiscales` | suma de todas las categorías / de todas menos bancos |
| `bancos_por_1000km2`, `pct_nacional_bancos` | densidad y participación nacional |
| `archivo_bronce_*`, `sha256_bronce_*`, `fecha_ingesta` | linaje |
