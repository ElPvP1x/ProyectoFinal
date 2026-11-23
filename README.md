# Observatorio Contabilidad y Cumplimiento Fiscal (México)

Proyecto integrador. Equipo: Cristopher Amaro Granero y Yerik Monroy García.

El observatorio se construye alrededor del **Sistema Contable (Auditor de CFDI 4.0)**, una herramienta web local en Python/Flask que lee descargas masivas del SAT (Excel o XML), aplica las reglas fiscales y entrega los montos auditados.

- **Capa Bronce:** datos económicos crudos (tipo de cambio, inflación, tasas) que afectan el trabajo del contador. Se capturan solos con GitHub Actions.
- **Capas Plata y Oro (E1):** limpieza, puerta de calidad con cuarentena e integración mensual. Se ejecutan solas después de cada captura.
- **Fuente geoespacial (E2):** infraestructura contable y fiscal de OpenStreetMap cruzada con las 32 entidades (geoBoundaries / INEGI) usando GeoPandas. Mapa en `docs/E2/mapa_infraestructura.png`.
- **Linaje (E2):** cada registro de Oro apunta a su archivo de Bronce, su hash y su fecha de ingesta (`datos/oro/linaje.csv`).
- **Documentos:** `docs/E0/` (propuesta), `docs/E1/` (cuaderno y ficha), `docs/E2/` (ficha y mapa), `docs/etica-datos.md`, `docs/relatoria-E1.md` y `docs/relatoria-E2.md`.

Ejecutar la captura: `BANXICO_TOKEN=... INEGI_TOKEN=... python src/extractor.py`
Revisar que haya 36 o más periodos: `python src/verificar_bronce.py`
Captura geoespacial (sin token): `python src/extractor_geo.py`
Bronce a Plata y Oro: `python src/pipeline.py` · Pruebas: `python -m pytest -q tests`
Rastrear un mes de Oro hasta Bronce: `python src/linaje.py 2024-06`

Fuentes citadas: Banco de México (SIE), INEGI (BIE), © colaboradores de OpenStreetMap (ODbL) y geoBoundaries (CC BY 3.0 IGO).
