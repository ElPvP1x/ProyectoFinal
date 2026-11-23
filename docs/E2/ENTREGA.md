# Ficha de entrega técnica — E2

| Campo | Valor |
|---|---|
| Equipo / integrantes | Cristopher Amaro Granero, Yerik Monroy García |
| Repositorio | https://github.com/ElPvP1x/ProyectoFinal |
| Tag | `e2` |
| Sector | Contabilidad y cumplimiento fiscal (Sistema Contable, Auditor de CFDI 4.0) |
| Fuente especializada elegida | **Geoespacial**, con dos fuentes cruzadas con GeoPandas: el **DENUE del INEGI** (establecimientos de contabilidad) y **OpenStreetMap** (bancos, oficinas del SAT y recaudadoras), sobre los polígonos de entidades de geoBoundaries / INEGI |
| Corrida de GitHub Actions | [pendiente: enlace a la corrida que descargó el DENUE] |

## Entregables

| Entregable | Ubicación | Estado |
|---|---|---|
| Extractores (se ejecutan en GitHub Actions) | `src/extractor_geo.py` · configuración en `config/fuentes.yml` (`inegi_denue`, `osm_overpass`, `geoboundaries`) | [x] |
| Bronce crudo | `datos/bronce/inegi_denue/` (zip del INEGI), `datos/bronce/osm_overpass/`, `datos/bronce/geoboundaries/` | [x] con hash en `manifiesto.csv` |
| Procesamiento con GeoPandas | `src/geo.py` (OSM y unión espacial), `src/denue.py` (DENUE) | [x] |
| Visualización cartográfica | `docs/E2/mapa_despachos_denue.png` (DENUE y cobertura de OSM), `docs/E2/mapa_infraestructura.png` (bancos, SAT y recaudadoras) | [x] |
| Plata y Oro geoespaciales | `datos/plata/geo_denue_contables.csv`, `datos/plata/geo_puntos.csv`, `datos/oro/geo_entidades.csv`, `datos/oro/geo_municipios.csv` | [x] |
| Declaración de ética y legalidad | `docs/etica-datos.md` | [x] términos, robots.txt, licencias, sesgos y privacidad |
| Linaje y trazabilidad | `src/linaje.py` · `datos/oro/linaje.csv` · columnas de linaje en Plata y Oro | [x] |
| Pruebas | `tests/test_e2.py` (9 nuevas) + `tests/test_pipeline.py` (9 de E1) | [x] 18 de 18 pasan |
| Relatoría de etapa | `docs/relatoria-E2.md` | [x] |
| Registros PSP | `calidad/tiempo-yerik.csv`, `calidad/defectos-yerik.csv` | [x] Yerik · [ ] Cristopher |

## 1. Fuente especializada: geoespacial

**Pregunta:** ¿dónde está la infraestructura que usa un contador (despachos, oficinas del SAT, recaudadoras y bancos) y qué tan desigual es su distribución entre entidades y municipios?

### Por qué dos fuentes

La primera versión usaba sólo OpenStreetMap. OSM tiene 88 despachos contables y asesores fiscales en todo el país; el DENUE tiene 16,936 establecimientos de contabilidad. Es decir, **OSM cubre el 0.52 %** de lo que registra el INEGI, y en 16 entidades no tiene ninguno. Por eso el DENUE es la fuente de los despachos y OSM se conserva para lo que el DENUE no clasifica igual: bancos, oficinas del SAT y recaudadoras estatales o municipales. La comparación entre las dos fuentes se publica como hallazgo (`cobertura_osm_pct`).

| Paso | DENUE (INEGI) | OpenStreetMap |
|---|---|---|
| Acceso | Descarga masiva del sector 54 (zip de 11 MB, sin token); GitHub Actions la baja como máximo cada 90 días | Una consulta a Overpass por corrida, con reintentos de 30 a 240 s |
| Filtro | SCIAN 541211 (servicios de contabilidad y auditoría) y 541219 (otros relacionados con la contabilidad) | `office=accountant`, `office=tax_advisor`, `government=tax`, nombre "SAT" o "Servicio de Administración Tributaria", `amenity=bank` |
| Campos que se leen | Lista blanca: id, clase, tamaño, entidad, municipio, coordenadas, fecha de alta | id, tipo, categoría y coordenadas |
| Calidad | coordenadas presentes, dentro de México, sin duplicados → cuarentena con motivo | igual, más categoría reconocida |
| Validación cruzada | La entidad que declara el DENUE se compara con la que da la unión espacial | — |

**Unión espacial:** `gpd.sjoin(puntos, entidades, predicate="within")`. Los puntos costeros que caen fuera del polígono simplificado se asignan a la entidad más cercana (≤ 5 km) con `sjoin_nearest` y quedan marcados en `asignacion`.

### Resultados de la prueba local del 23 de noviembre de 2026

La captura oficial del DENUE la descarga GitHub Actions; estas cifras salen del mismo archivo bajado localmente para probar (DENUE 05_2026, publicado el 20 de mayo de 2026).

| Medida | Valor |
|---|---|
| Establecimientos de contabilidad en el DENUE | 16,936 (16,356 de la clase 541211 y 580 de la 541219); 0 en cuarentena |
| Con 11 o más personas ocupadas | 1,688 (10 %) |
| Concordancia de entidad (DENUE contra unión espacial) | 99.99 % |
| Municipios con al menos un despacho | 992 |
| Entidades con más despachos | Ciudad de México 1,248 · Jalisco 1,241 · Veracruz 1,029 · Estado de México 1,023 · Michoacán 894 |
| Municipios con más despachos | Guadalajara 432 · Monterrey 425 · Tijuana 381 · Puebla 337 · Benito Juárez (CDMX) 299 |
| Concentración | las 5 primeras entidades tienen el 32.1 % de los despachos, contra el 48.6 % de los bancos: los despachos están menos concentrados |
| Densidad | Ciudad de México: 839.7 despachos por 1,000 km² |
| Elementos de OSM | 5,234: 5,025 bancos, 83 despachos, 63 oficinas del SAT, 58 recaudadoras locales, 5 asesores fiscales; 0 en cuarentena |
| Cobertura de OSM frente al DENUE | 0.52 % nacional; 0 % en 16 entidades (por ejemplo Colima: 186 en el DENUE, 0 en OSM) |

## 2. Linaje y trazabilidad

Cada registro de Oro se rastrea hasta su archivo de Bronce y su fecha de ingesta.

| Capa | Qué lleva cada registro |
|---|---|
| Bronce | archivo `<captura>.json` o `.zip` + fila en `manifiesto.csv` con bytes y SHA-256 |
| Plata (series) | `origen` (`bronce` o `imputado (interpolacion)`), `fecha_ingesta`, `archivo_bronce`, `sha256_bronce` |
| Plata (geo) | lo mismo por cada punto, más el id del DENUE o el id de OSM para ubicar el registro original |
| Oro mensual | `fecha_ingesta`, `archivos_bronce` (todos los archivos que formaron el mes), `registros_bronce` |
| Oro geo | archivo y hash de cada fuente (`*_puntos`, `*_entidades`, `*_denue`) y `fecha_ingesta` |
| Detalle | `datos/oro/linaje.csv`: una fila por (mes, serie), con registros de Bronce aportados, imputados y rango de fechas |

**Integridad.** Antes de usar un archivo de Bronce se recalcula su SHA-256 y se compara con el manifiesto. Si no coincide o el archivo no está registrado, el pipeline se detiene (`linaje.ficha_archivo`). El `.gitattributes` evita que Git cambie los fines de línea de los JSON y los zip, para que el hash siga siendo válido en cualquier sistema.

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

- **Licencias:** Banxico (citar fuente), INEGI y DENUE (Términos de Libre Uso), OSM (ODbL 1.0), geoBoundaries (CC BY 3.0 IGO). La atribución va en cada mapa.
- **robots.txt:** permitidas las rutas de Banxico, INEGI (API y descarga masiva) y geoBoundaries. Overpass bloquea `/api/` para rastreadores; nuestro uso es una consulta semanal dentro de su política, con User-Agent propio y espera creciente ante 429 o 5xx.
- **Privacidad:** el DENUE trae nombre, teléfono, correo y domicilio de personas físicas; se leen sólo las columnas de una lista blanca y una prueba lo verifica. Oro está agregado por entidad y municipio.
- **Sesgos:** cobertura de OSM (0.52 % frente al DENUE), actualización desigual del DENUE, tamaño de las entidades, etiquetado inconsistente y polígonos simplificados, cada uno con su mitigación.

## 4. Objetivos de calidad medibles (E2)

1. **100 % de los registros de Oro con linaje completo:** `test_cada_registro_de_oro_es_rastreable`. Resultado: 190 de 190 meses y 32 de 32 entidades.
2. **Cero datos personales en Plata y Oro geoespaciales:** `test_geo_descarta_datos_personales_y_manda_a_cuarentena` y `test_denue_sin_datos_personales_y_con_cuarentena`. Resultado: ninguna columna de nombre, teléfono, correo o domicilio.
3. **Concordancia geográfica ≥ 99 %** entre la entidad declarada en el DENUE y la unión espacial. Resultado: 99.99 %.

## Cómo reproducir

```
pip install -r requirements.txt
python src/extractor_geo.py        # DENUE, OSM y geoBoundaries (sin token)
python src/pipeline.py             # Bronce -> Plata -> Oro (series y geo) + mapas
python -m pytest -q tests
python src/linaje.py 2024-06       # rastrea un mes de Oro hasta Bronce
```

## Diccionario de `datos/oro/geo_entidades.csv`

| Columna | Descripción |
|---|---|
| `entidad`, `clave_iso` | nombre y clave ISO 3166-2 de la entidad |
| `area_km2` | área calculada en EPSG:6372 |
| `denue_contables`, `denue_contables_11_o_mas` | establecimientos de contabilidad del DENUE, total y con 11 o más personas |
| `denue_por_1000km2`, `pct_nacional_denue` | densidad y participación nacional de los despachos |
| `despacho_contable`, `asesor_fiscal`, `oficina_sat`, `recaudacion_local`, `banco` | conteo de elementos de OSM por categoría |
| `cobertura_osm_pct` | despachos y asesores de OSM como % de los del DENUE |
| `bancos_por_1000km2`, `pct_nacional_bancos` | densidad y participación nacional de los bancos |
| `archivo_bronce_*`, `sha256_bronce_*`, `fecha_ingesta` | linaje de cada fuente |

`datos/oro/geo_municipios.csv` tiene una fila por municipio con despachos: `cve_geo` (clave del Marco Geoestadístico), entidad, municipio, conteos y linaje.
