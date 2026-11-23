# Declaración de ética y legalidad de los datos

**Observatorio Contabilidad y Cumplimiento Fiscal** · Cristopher Amaro Granero y Yerik Monroy García · E2

Este documento explica con qué permiso usamos cada fuente, qué reglas respetamos al consultarla, qué sesgos tienen los datos y cómo protegemos la privacidad. Se revisa en cada etapa.

## 1. Inventario de fuentes

| Fuente | Qué tomamos | Acceso | Licencia o términos | Atribución que mostramos |
|---|---|---|---|---|
| Banco de México, SIE API | FIX, TIIE 28 días, UDIS, INPC | API REST con token personal (`BANXICO_TOKEN`) | Términos de uso del SIE API: la información es pública y se usa citando a Banco de México como fuente; el token es personal y no se comparte | "Fuente: Banco de México, Sistema de Información Económica" |
| INEGI, Banco de Indicadores (BIE) | INPC (para contrastar con Banxico) | API con token (`INEGI_TOKEN`); hoy sin captura porque falta el token | Términos de libre uso de la información del INEGI: se permite usar, copiar y redistribuir citando al INEGI | "Fuente: INEGI, Banco de Indicadores" |
| OpenStreetMap vía Overpass API (E2) | Ubicación y categoría de despachos contables, asesores fiscales, oficinas del SAT y bancos | API pública sin token, `overpass-api.de` | Open Database License (ODbL 1.0) | "© colaboradores de OpenStreetMap" en el mapa y en los CSV derivados |
| geoBoundaries, gbOpen MEX ADM1 (E2) | Polígonos de las 32 entidades | API pública sin token; archivo en GitHub | CC BY 3.0 IGO; los límites provienen del Marco Geoestadístico del INEGI | "Límites: geoBoundaries / INEGI" |

La licencia de geoBoundaries se tomó del campo `boundaryLicense` de su propia API y queda guardada en el log del extractor. Las demás se verificaron en los portales de cada institución al iniciar el proyecto; si cambian, se actualiza esta tabla.

## 2. Análisis de robots.txt

Revisado el 23 de noviembre de 2026 con el mismo User-Agent que usan los extractores.

| Sitio | Regla relevante | Ruta que usamos | Conclusión |
|---|---|---|---|
| `www.banxico.org.mx` | `Disallow: /dyn/` y `/ALEPH` | `/SieAPIRest/service/v1/series` | Permitida: la ruta de la API no está restringida |
| `www.inegi.org.mx` | `Allow: /app` (y otras secciones) | `/app/api/indicadores/...` | Permitida explícitamente |
| `www.geoboundaries.org` | `Crawl-delay: 10`; sólo bloquea rutas administrativas | `/api/current/gbOpen/MEX/ADM1/` | Permitida; hacemos una sola petición y sólo cuando no hay captura previa |
| `overpass-api.de` | `Disallow: /api/` para todo agente | `/api/interpreter` | **Restringida para rastreadores.** Ver abajo |
| `github.com` | `Crawl-delay: 1` | descarga directa del GeoJSON | Una descarga, sólo la primera vez |

**El caso de Overpass.** Su robots.txt pide a los rastreadores (buscadores e indexadores) no recorrer `/api/`. Nosotros no rastreamos: hacemos una consulta puntual, igual que una persona en overpass-turbo. Lo que regula ese uso es la política de uso de la instancia pública, que permite el uso razonable (del orden de 10,000 consultas o 1 GB al día) y pide no saturar el servicio. Para mantenernos muy por debajo de ese límite:

- Una sola consulta por corrida, una vez por semana (el workflow corre los lunes).
- User-Agent que identifica el proyecto, sin hacerse pasar por navegador.
- Reintentos con espera creciente (30, 60, 120 y 240 s) cuando el servidor responde 429, 502, 503 o 504, como pide el propio mensaje de error.
- Si la consulta falla, el pipeline usa la captura anterior en lugar de insistir.

En la prueba del 23 de noviembre el servidor respondió que estaba saturado y recomendó instalar una instancia propia para uso automatizado. Si el proyecto creciera a consultas diarias, migraríamos a un extracto de Geofabrik procesado localmente o al DENUE del INEGI, que además tiene mejor cobertura (ver sección 3).

## 3. Sesgos y cómo los mitigamos

| Sesgo | Dónde aparece | Mitigación |
|---|---|---|
| **Cobertura desigual de OpenStreetMap** | OSM depende de voluntarios. Hay muchos más despachos contables reales que los registrados, y la cobertura es mejor en ciudades grandes | No se presentan los conteos como "número de despachos en México", sino como "registrados en OSM". El mapa usa bancos (mejor cubiertos) como capa principal y los despachos como puntos. Se documenta el DENUE como referencia oficial para comparar |
| **Tamaño de la entidad** | Los conteos brutos favorecen a los estados grandes | Se reporta densidad por 1,000 km² y porcentaje nacional, no sólo totales |
| **Etiquetado inconsistente** | Una oficina del SAT puede estar como `government=tax` o sólo con el nombre | La categoría se asigna con reglas explícitas en `geo.categoria()`, y lo que no encaja va a cuarentena con motivo, no se descarta en silencio |
| **Polígonos simplificados** | Puntos en la costa pueden caer fuera del polígono | Se asignan a la entidad más cercana (máximo 5 km) y la columna `asignacion` lo indica |
| **Indicadores agregados nacionales** | El INPC y la TIIE son promedios nacionales; no reflejan la realidad de un contribuyente en particular | El observatorio no hace afirmaciones individuales; se usa para contexto del trabajo contable |
| **Imputación** | 3.6 % de días sin FIX o TIIE se rellenan por interpolación | Cada fila imputada lleva `imputado = True` y `origen = imputado (interpolacion)` en Plata |

## 4. Privacidad

- **Cero datos personales.** Las series de Banxico e INEGI son agregados macroeconómicos. De OpenStreetMap sólo se conservan el identificador del elemento, su tipo, la categoría y las coordenadas. El nombre, el teléfono, el correo, el sitio web y la dirección se descartan al leer Bronce; la prueba `test_geo_descarta_datos_personales_y_manda_a_cuarentena` lo verifica con un lote que sí trae nombre y teléfono.
- **Agregación.** Un despacho contable puede ser el domicilio de una persona física. Por eso el producto de Oro (`geo_entidades.csv`) está agregado por entidad federativa y el mapa no lleva etiquetas.
- **Bronce crudo.** La respuesta de Overpass se guarda tal cual llega para poder auditarla, y puede incluir el nombre de un negocio que el propio negocio publicó en OSM. Es información pública bajo ODbL, pero no se usa ni se propaga a Plata u Oro.
- **CFDI del Sistema Contable.** Las facturas que procesa el Auditor de CFDI contienen RFC y montos de personas reales. **No forman parte de este repositorio** ni del observatorio; el Sistema Contable las procesa en local.
- **Secretos.** Los tokens de Banxico e INEGI viven como secretos de GitHub Actions. El extractor nunca los imprime, ni siquiera en los mensajes de error.

## 5. Trazabilidad como garantía

Cada registro de Oro se puede rastrear hasta el archivo crudo de Bronce y su fecha de ingesta (`datos/oro/linaje.csv`, `python src/linaje.py <mes>`). El hash SHA-256 de cada archivo se compara con `datos/bronce/manifiesto.csv`; si un archivo se modificara después de capturarse, el pipeline se detiene. Esto permite a cualquier revisor comprobar que los resultados vienen de los datos publicados por la fuente y no fueron alterados.

## 6. Uso responsable de los resultados

- Los resultados son para fines académicos y de contexto contable; no son asesoría fiscal ni financiera.
- Toda gráfica o tabla publicada lleva su fuente y su fecha de captura.
- Si una institución pide dejar de consultar su servicio, se desactiva la fuente con `activa: false` en `config/fuentes.yml`.
