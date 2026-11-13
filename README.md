# Observatorio Contabilidad y Cumplimiento Fiscal (México)

Proyecto integrador. Equipo: Cristopher Amaro Granero y Yerik Monroy García.

El observatorio se construye alrededor del **Sistema Contable (Auditor de CFDI 4.0)**, una herramienta web local en Python/Flask que lee descargas masivas del SAT (Excel o XML), aplica las reglas fiscales y entrega los montos auditados.

- **Capa Bronce:** datos económicos crudos (tipo de cambio, inflación, tasas) que afectan el trabajo del contador. Se capturan solos con GitHub Actions.
- **Documentos de la entrega E0:** carpeta `docs/E0/`.

Ejecutar la captura: `BANXICO_TOKEN=... INEGI_TOKEN=... python src/extractor.py`
Revisar que haya 36 o más periodos: `python src/verificar_bronce.py`

Fuentes citadas: Banco de México (SIE) e INEGI (BIE).
