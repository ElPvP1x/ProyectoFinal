# Propuesta del Observatorio — Vivienda y Precios

## 1. Ficha del observatorio

| Campo | Contenido |
|---|---|
| Sector | Vivienda: precios de compra y costo del financiamiento hipotecario |
| Región | México (nivel nacional; en E3 se compararán estados o ciudades) |
| Pregunta detonadora | ¿Cómo se va a comportar el precio de la vivienda en México en los próximos 6 a 12 meses y qué factores lo mueven más (tasas, inflación, ingreso, oferta)? |
| Cliente potencial | Desarrolladoras, inmobiliarias, corredores y familias que planean comprar y necesitan decidir cuándo comprar, vender, construir o contratar un crédito |
| Integrantes | Cristopher Amaro Granero, Yerik Monroy García |

### 1.1 Contexto y justificación

Para la mayoría de los hogares la vivienda es la compra más grande de su vida y se paga con un crédito a 15 o 20 años, así que una variación en el precio o en la tasa hipotecaria cambia el enganche, la mensualidad y hasta si la familia califica para el crédito. Del lado de la oferta, una desarrolladora vende uno o dos años después de iniciar un proyecto, por lo que su rentabilidad depende de cómo se muevan precios y tasas en ese intervalo.

La información existe, pero está dispersa y llega con rezago: los índices de precios de vivienda son trimestrales y se publican semanas después, la inflación y las tasas salen en otros sitios, y los portales inmobiliarios muestran precios de oferta, no de cierre. El observatorio junta las fuentes oficiales, las actualiza de forma automática y las convierte en un pronóstico, una explicación de los factores y una comparación entre regiones. El primer cliente con el que se validará es el agente inmobiliario o asesor hipotecario, porque está en contacto con desarrolladoras y compradores.

## 2. Entrevista de campo (mínimo 15 min)

**Estado: pendiente.** La entrevista de campo no se alcanzó a realizar antes de la fecha de entrega de E0. No se incluyen respuestas simuladas ni inventadas. El guion completo está en [guion-entrevista.md](guion-entrevista.md) y el formato de registro en [notas-entrevista.md](notas-entrevista.md). Se realizará con un agente inmobiliario o asesor hipotecario y se actualizará esta sección, junto con la pregunta detonadora y los factores de E2, en cuanto se cuente con ella.

Preguntas que se harán (5):

1. ¿Cuál es la decisión del año que más le preocupa (comprar, vender, construir, financiar) y qué dato le gustaría tener antes de tomarla?
2. ¿Cómo se entera hoy de los precios de la vivienda y qué tan confiable le parece esa fuente?
3. ¿Qué factores (tasas de interés, temporada, zona, oferta de nuevos desarrollos) le suben o le bajan más los precios?
4. ¿Qué pasó la última vez que se equivocó en el precio o en la tasa esperada y cuánto le costó?
5. Si le diéramos un pronóstico mensual de precios de vivienda, ¿cómo lo usaría y cuánto estaría dispuesto a pagar por él?

**Respuestas:** pendiente.

**Aprendizajes:** pendiente.

## 3. Las 3 preguntas analíticas

| Etapa | Pregunta | Detalle |
|---|---|---|
| E1 Pronóstico | ¿Cuál será el índice de precios de la vivienda en México en los próximos 6 a 12 meses? | Variable a pronosticar: índice de precios de vivienda (serie de tiempo, 36+ periodos) |
| E2 Experimentos | ¿Qué factores cambian significativamente el precio o la demanda? | Factores: tipo de vivienda (nueva / usada), rango de tasa hipotecaria, trimestre del año, con 2 o 3 niveles cada uno |
| E3 Multivariado | ¿Qué estados o ciudades se parecen en su comportamiento? | Grupos a comparar: estados o ciudades de México usando varias variables a la vez (precio, variación anual, inflación de vivienda, tasa, volatilidad) |

### 3.1 Hipótesis, método y criterio de éxito

* **E1:** se espera una tendencia creciente que responde con rezago a la inflación y a la tasa. Se compararán un modelo ingenuo, Holt-Winters y SARIMA con los últimos 6 a 8 periodos como prueba; el éxito es un MAPE menor que el del modelo ingenuo y un pronóstico con intervalo de confianza.
* **E2:** se espera que el tipo de vivienda y el nivel de tasa tengan efecto significativo y el trimestre uno menor. Se analizará un diseño factorial con ANOVA (verificando normalidad y varianzas) al 5 % de significancia.
* **E3:** se espera que los estados formen pocos grupos (mercados de alza rápida y volátiles frente a estables). Se estandarizarán las variables, se aplicará PCA y k-medias o clúster jerárquico, eligiendo el número de grupos con el codo y la silueta.

## 4. Plan de recopilación de datos

| # | Fuente | Qué se descarga | Frecuencia | Método |
|---|---|---|---|---|
| 1 | Banxico, Sistema de Información Económica (API) | INPC general mensual (serie SP1, desde 2010, 202 periodos ya capturados). Series de vivienda (índice de precios, tasas hipotecarias) por confirmar en el catálogo SIE y agregar a `config/fuentes.yml` | Semanal por Actions | API oficial con token gratuito |
| 2 | INEGI, Banco de Indicadores (API) | Indicadores de INPC vivienda por ciudad/entidad (IDs por confirmar; fuente aún inactiva en `fuentes.yml`) | Semanal por Actions | API oficial con token gratuito |

### Análisis ético y legal

| Fuente | robots.txt (url y fecha de revisión) | Términos de uso | Conclusión |
|---|---|---|---|
| Banxico SIE | https://www.banxico.org.mx/robots.txt — revisado el 8-nov-2026. Solo prohíbe `/dyn`, `/dyn/` y `/ALEPH`; la ruta `/SieAPIRest` no está vetada. | https://www.banxico.org.mx/footer-es/salvedad-politicas-uso-banco-.html — Banxico autoriza de forma general usar y reproducir su información, a condición de citar la fuente y la dirección de internet; no asume responsabilidad por el uso de terceros ni autoriza revender sus datos como propios. | Se usa la API oficial con token propio, 1 consulta por serie, con pausa de 2 s |
| INEGI BIE | https://www.inegi.org.mx/robots.txt — revisado el 8-nov-2026. Permite `/app` (donde vive la API); solo prohíbe rutas de catálogo y descarga del RNM, que no usamos. | https://www.inegi.org.mx/inegi/terminos.html — Permite copiar, adaptar y explotar la información conservando metadatos; hay que citar "Fuente: INEGI, [producto]", avisar si se hizo análisis o transformación y no sugerir aval del INEGI. | Se usa la API oficial con token propio, con pausa de 2 s |

Reglas que seguimos: identificarnos con User-Agent, no pasar de 1 solicitud cada 2 segundos, no tocar datos personales, citar la fuente y guardar los datos crudos sin modificar.

## 5. Arquitectura de datos

```
APIs ──▶ Bronce (crudo) ──▶ Plata (validado) ──▶ Oro (análisis)
```

* **Bronce (E0, en operación):** la respuesta de cada API tal como llegó, con fecha y hash SHA-256 en `manifiesto.csv`; nunca se modifica. Hoy contiene 202 periodos mensuales del INPC general (enero 2010 a octubre 2026), capturados cada lunes con GitHub Actions.
* **Plata (E1):** series limpias, con fechas y valores numéricos, sin duplicados y con una puerta de calidad que rechaza capturas incompletas.
* **Oro (E3):** tablas listas para cada pregunta: la serie para E1, la tabla factorial para E2 y la matriz estado × variable para E3.

## 6. Riesgos principales

* **La serie capturada (INPC general) no mide el precio de la vivienda.** Antes de E1 se agregarán el índice de precios de vivienda (por ejemplo, el de la Sociedad Hipotecaria Federal) y el INPC de vivienda de INEGI; como son trimestrales, se usará la serie más larga para cumplir los 36 periodos.
* **La API cambia de formato o se cae.** El crudo se guarda tal cual y la limpieza vive en Plata, así que un cambio no destruye lo capturado; el workflow marca error y queda registrado.
* **La entrevista no confirma la pregunta detonadora.** Se ajustarán la pregunta y los factores de E2 antes de iniciar E1.
