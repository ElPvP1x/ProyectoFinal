# Observatorio Contabilidad y Cumplimiento Fiscal (México)

Proyecto integrador. Equipo: Cristopher Amaro Granero y Yerik Monroy García.

El observatorio se construye alrededor del **Sistema Contable (Auditor de CFDI 4.0)**, una herramienta web local en Python/Flask que lee descargas masivas del SAT (Excel o XML), aplica las reglas fiscales y entrega los montos auditados.

- **Capa Bronce:** datos económicos crudos (tipo de cambio, inflación, tasas) que afectan el trabajo del contador. Se capturan solos con GitHub Actions.
- **Sistema Contable:** carpeta `sistema_contable/` (código, reglas fiscales y pruebas). Se arranca con `python app.py` dentro de esa carpeta. Los datos reales de clientes no se suben (ver su `.gitignore`).
- **Capas Plata y Oro (E1):** limpieza, puerta de calidad con cuarentena e integración mensual. Se ejecutan solas después de cada captura.
- **Documentos:** `docs/E0/` (propuesta), `docs/E1/` (cuaderno y ficha) y `docs/relatoria-E1.md`.

Ejecutar la captura: `BANXICO_TOKEN=... INEGI_TOKEN=... python src/extractor.py`
Revisar que haya 36 o más periodos: `python src/verificar_bronce.py`
Bronce a Plata y Oro: `python src/pipeline.py` · Pruebas: `python -m pytest -q tests`

Fuentes citadas: Banco de México (SIE) e INEGI (BIE).
