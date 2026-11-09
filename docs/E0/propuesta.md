# Propuesta del Observatorio — Vivienda y Precios

> Los textos entre [CORCHETES] los tienen que completar ustedes. Lo demás es un borrador listo para ajustar.

## 1. Ficha del observatorio

| Campo | Contenido |
|---|---|
| Sector | Vivienda: precios de compra y costo del financiamiento hipotecario |
| Región | [México / su estado o ciudad] |
| Pregunta detonadora | ¿Cómo se va a comportar el precio de la vivienda en [región] en los próximos 6 a 12 meses y qué factores lo mueven más (tasas, inflación, ingreso, oferta)? |
| Cliente potencial | [Desarrolladora, inmobiliaria, corredor o familia que planea comprar] que necesita decidir cuándo comprar, vender, construir o contratar un crédito |
| Integrantes | [Nombre 1], [Nombre 2] |

## 2. Entrevista de campo (mínimo 15 min)

Entrevistado: [nombre, ocupación, empresa]. Fecha: [__]. Duración: [__ min]. Medio: [presencial / llamada].

Posibles entrevistados: agente inmobiliario, desarrollador, valuador, asesor hipotecario, o alguien que compró vivienda hace poco.

Preguntas sugeridas (cámbienlas por las que realmente hagan):

1. ¿Cuál es la decisión del año que más le preocupa (comprar, vender, construir, financiar) y qué dato le gustaría tener antes de tomarla?
2. ¿Cómo se entera hoy de los precios de la vivienda y qué tan confiable le parece esa fuente?
3. ¿Qué factores (tasas de interés, temporada, zona, oferta de nuevos desarrollos) le suben o le bajan más los precios?
4. ¿Qué pasó la última vez que se equivocó en el precio o en la tasa esperada y cuánto le costó?
5. Si le diéramos un pronóstico mensual de precios de vivienda, ¿cómo lo usaría y cuánto estaría dispuesto a pagar por él?

**Respuestas:** [resumen de cada una, con frases textuales cortas].

**Aprendizajes:** [3 a 5 cosas que cambiaron o confirmaron su pregunta].

## 3. Las 3 preguntas analíticas

| Etapa | Pregunta | Detalle |
|---|---|---|
| E1 Pronóstico | ¿Cuál será el índice de precios de la vivienda en [región] en los próximos 6 a 12 meses? | Variable a pronosticar: índice de precios de vivienda (serie de tiempo, 36+ periodos) |
| E2 Experimentos | ¿Qué factores cambian significativamente el precio o la demanda? | Factores: [tipo de vivienda (nueva / usada), rango de tasa hipotecaria, trimestre del año], con 2 o 3 niveles cada uno |
| E3 Multivariado | ¿Qué estados o ciudades se parecen en su comportamiento? | Grupos a comparar: [estados o ciudades] usando varias variables a la vez (precio, variación anual, inflación de vivienda, tasa, volatilidad) |

## 4. Plan de recopilación de datos

| # | Fuente | Qué se descarga | Frecuencia | Método |
|---|---|---|---|---|
| 1 | Banxico, Sistema de Información Económica (API) | [Series de vivienda: índice de precios, INPC subíndice vivienda, tasas hipotecarias — IDs por confirmar en el catálogo SIE] | Semanal por Actions | API oficial con token gratuito |
| 2 | INEGI, Banco de Indicadores (API) | [Indicadores de INPC vivienda por ciudad/entidad — IDs por confirmar] | Semanal por Actions | API oficial con token gratuito |

### Análisis ético y legal

| Fuente | robots.txt (url y fecha de revisión) | Términos de uso | Conclusión |
|---|---|---|---|
| Banxico SIE | https://www.banxico.org.mx/robots.txt — revisado el 8-nov-2026. Solo prohíbe `/dyn`, `/dyn/` y `/ALEPH`; la ruta `/SieAPIRest` no está vetada. | [url de términos — copiar qué dicen sobre uso y límites de la API] | Se usa la API oficial con token propio, 1 consulta por serie, con pausa de 2 s |
| INEGI BIE | https://www.inegi.org.mx/robots.txt — revisado el 8-nov-2026. Permite `/app` (donde vive la API); solo prohíbe rutas de catálogo y descarga del RNM, que no usamos. | [url de términos — copiar resumen] | Se usa la API oficial con token propio, con pausa de 2 s |

Reglas que seguimos: identificarnos con User-Agent, no pasar de 1 solicitud cada 2 segundos, no tocar datos personales, citar la fuente y guardar los datos crudos sin modificar.
