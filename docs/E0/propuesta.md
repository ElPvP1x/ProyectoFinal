# Propuesta del Observatorio — Agro y Precios

> Los textos entre [CORCHETES] los tienen que completar ustedes. Lo demás es un borrador listo para ajustar.

## 1. Ficha del observatorio

| Campo | Contenido |
|---|---|
| Sector | Agropecuario: precios de alimentos frescos |
| Región | [México / su estado] |
| Pregunta detonadora | ¿Cómo se van a comportar los precios de [producto, p. ej. limón/aguacate/jitomate] en los próximos 6 meses y qué factores los mueven más? |
| Cliente potencial | [Productor, empacadora o comerciante de la región] que necesita decidir cuándo sembrar, cosechar o vender |
| Integrantes | [Nombre 1], [Nombre 2] |

## 2. Entrevista de campo (mínimo 15 min)

Entrevistado: [nombre, ocupación, empresa/parcela]. Fecha: [__]. Duración: [__ min]. Medio: [presencial / llamada].

Preguntas sugeridas (cámbienlas por las que realmente hagan):

1. ¿Cuál es la decisión del año que más le preocupa y qué dato le gustaría tener antes de tomarla?
2. ¿Cómo se entera hoy de los precios y qué tan confiable le parece esa fuente?
3. ¿Qué meses o situaciones le suben o le bajan más el precio de lo que vende?
4. ¿Qué pasó la última vez que se equivocó en el precio esperado y cuánto le costó?
5. Si le diéramos un pronóstico mensual de precios, ¿cómo lo usaría y cuánto estaría dispuesto a pagar por él?

**Respuestas:** [resumen de cada una, con frases textuales cortas].

**Aprendizajes:** [3 a 5 cosas que cambiaron o confirmaron su pregunta; ej. "el precio importa por kilo puesto en mercado, no en parcela"].

## 3. Las 3 preguntas analíticas

| Etapa | Pregunta | Detalle |
|---|---|---|
| E1 Pronóstico | ¿Cuál será el precio mensual de [producto] en los próximos 6 meses? | Variable a pronosticar: precio medio mensual (serie de tiempo, 36+ periodos) |
| E2 Experimentos | ¿Qué factores cambian significativamente el precio? | Factores: [mes/temporada, tipo de mercado, estado de origen], con 2 o 3 niveles cada uno |
| E3 Multivariado | ¿Qué grupos de productos o estados se parecen en su comportamiento? | Grupos a comparar: [productos o estados] usando varias variables a la vez (precio, volumen, variabilidad) |

## 4. Plan de recopilación de datos

| # | Fuente | Qué se descarga | Frecuencia | Método |
|---|---|---|---|---|
| 1 | Banxico, Sistema de Información Económica (API) | Series de INPC (SP1 y series de alimentos) desde 2010 | Semanal por Actions | API oficial con token gratuito |
| 2 | [INEGI BIE / SNIIM / SIAP] | [indicador o producto concreto] | Semanal por Actions | [API o descarga abierta] |

### Análisis ético y legal (llenar tras revisar cada sitio)

| Fuente | robots.txt (url y fecha de revisión) | Términos de uso | Conclusión |
|---|---|---|---|
| Banxico SIE | [https://www.banxico.org.mx/robots.txt — revisado el __] | [url de términos — qué dicen sobre uso y límites de la API] | Se usa la API oficial con token propio, 1 consulta por serie, con pausa de 2 s |
| [Fuente 2] | [url — fecha] | [url — resumen] | [permitido / permitido con límites / no se usa] |

Reglas que seguimos: identificarnos con User-Agent, no pasar de 1 solicitud cada 2 segundos, no tocar datos personales, citar la fuente y guardar los datos crudos sin modificar.

> Nota: desde la herramienta con la que se preparó este borrador no se pudieron abrir los sitios del gobierno, así que el contenido de robots.txt y términos lo tienen que revisar y copiar ustedes.
