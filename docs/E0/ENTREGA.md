# Ficha de entrega técnica — E0

| Campo | Valor |
|---|---|
| Equipo / integrantes | Cristopher Amaro Granero, Yerik Monroy García |
| Repositorio | https://github.com/ElPvP1x/ProyectoFinal |
| Tag | `e0` |
| Sector | Contabilidad y cumplimiento fiscal (Sistema Contable, Auditor de CFDI 4.0) |
| Profesores agregados como colaboradores | [usuario 1], [usuario 2], [usuario 3] |

## Entregables

| Entregable | Ubicación | Estado |
|---|---|---|
| Propuesta | `docs/E0/propuesta.md` | [ ] incompleta: entrevista de campo pendiente (ver sección 2) |
| Extractor | `src/extractor.py` | [x] captura Banxico (FIX, INPC, TIIE, UDIS) e INEGI (INPC) |
| Automatización | `.github/workflows/captura.yml` | [ ] actualizado con INEGI_TOKEN y verificación; falta correrlo de nuevo en Actions |
| Serie histórica Bronce (≥ 36 periodos) | `datos/bronce/` y `datos/bronce/manifiesto.csv` | [ ] INPC ya tiene 202 periodos; confirmar con `python src/verificar_bronce.py` tras la nueva captura |
| Registros PSP | `calidad/tiempo-*.csv`, `calidad/defectos-*.csv` | [x] archivos creados; falta registrar tiempos y defectos reales |

## 3 objetivos de calidad medibles

1. Cero ejecuciones fallidas del workflow en las últimas 4 corridas semanales (meta: 100 % exitosas).
2. Cada archivo crudo registrado en el manifiesto con su hash SHA-256 (meta: 100 % de archivos).
3. Máximo 1 defecto por cada 100 líneas de código, medido con `calidad/defectos-*.csv` (meta: ≤ 1/100).

## Cómo reproducir

```
pip install -r requirements.txt
BANXICO_TOKEN=... INEGI_TOKEN=... python src/extractor.py
python src/verificar_bronce.py
```
