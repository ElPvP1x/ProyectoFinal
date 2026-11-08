# Ficha de entrega técnica — E0

| Campo | Valor |
|---|---|
| Equipo / integrantes | [Nombre 1], [Nombre 2] |
| Repositorio | [url] |
| Tag | `e0` |
| Profesores agregados como colaboradores | [usuario 1], [usuario 2], [usuario 3] |

## Entregables

| Entregable | Ubicación | Estado |
|---|---|---|
| Propuesta | `docs/E0/propuesta.md` | [ ] |
| Extractor | `src/extractor.py` | [ ] |
| Automatización | `.github/workflows/captura.yml` | [ ] corrió con éxito (link a la ejecución) |
| Serie histórica Bronce (≥ 36 periodos) | `datos/bronce/` y `datos/bronce/manifiesto.csv` | [ ] periodos: [__] |
| Registros PSP | `calidad/tiempo-*.csv`, `calidad/defectos-*.csv` | [ ] |

## 3 objetivos de calidad medibles

1. Cero ejecuciones fallidas del workflow en las últimas 4 corridas semanales (meta: 100 % exitosas).
2. Cada archivo crudo registrado en el manifiesto con su hash SHA-256 (meta: 100 % de archivos).
3. Máximo 1 defecto por cada 100 líneas de código, medido con `calidad/defectos-*.csv` (meta: ≤ 1/100).

## Cómo reproducir

```
pip install -r requirements.txt
BANXICO_TOKEN=... python src/extractor.py
```
