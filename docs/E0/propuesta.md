# Propuesta del Observatorio — Contabilidad y Cumplimiento Fiscal

## 1. Ficha del observatorio

| Campo | Contenido |
|---|---|
| Sector | Contabilidad y cumplimiento fiscal: auditoría de comprobantes fiscales (CFDI 4.0) y variables económicas que afectan el trabajo del contador |
| Región | México (nivel nacional) |
| Pregunta detonadora | ¿Cómo se va a comportar el tipo de cambio USD/MXN en los próximos 6 meses y cuánto cambia el total deducible de un contribuyente según el criterio fiscal que use el contador (tipo de cambio, notas de crédito, tope de efectivo, IVA por defecto)? |
| Cliente potencial | Contadores independientes, despachos contables y PyMEs que facturan o reciben pagos en dólares y necesitan decidir qué tipo de cambio usar y cuánto pueden deducir |
| Integrantes | Cristopher Amaro Granero, Yerik Monroy García |

### Producto base: Sistema Contable (Auditor de CFDI 4.0)

El observatorio no parte de cero. Ya existe un sistema web local en Python (Flask y pandas) que:

- Lee descargas masivas del SAT en Excel o XML (incluido el `.zip`).
- Clasifica los archivos en Emitidas, Recibidas, Egresos, Pagos y Nóminas.
- Aplica las reglas fiscales (notas de crédito, facturas PPD, tope de efectivo de $2,000, lista de conceptos no deducibles, cancelados y duplicados).
- Convierte todo a pesos con el tipo de cambio y entrega el total deducible y un Excel depurado.

Toda la parametrización fiscal vive en `config_reglas.json`. Eso es lo que permite hacer experimentos en E2: cada parámetro es un factor que se puede mover sin tocar el código.

## 2. Entrevista de campo (mínimo 15 min)

**Estado: pendiente.** No se incluyen respuestas simuladas ni inventadas. El guion está en [guion-entrevista.md](guion-entrevista.md) y el formato de registro en [notas-entrevista.md](notas-entrevista.md). Se hará con un contador público, un despacho contable o el dueño de una PyME que lleve su propia contabilidad, y al terminar se actualizan esta sección, la pregunta detonadora y los factores de E2.

Preguntas que se harán (5):

1. ¿Cuál es la parte de su trabajo que más tiempo le quita en el mes (revisar facturas, declarar, conciliar, otra) y qué dato le gustaría tener antes de empezar?
2. ¿Cómo revisa hoy las facturas que descarga del SAT y qué tan confiable le parece ese proceso?
3. ¿Qué situaciones le cambian más el monto que puede deducir (notas de crédito, facturas en parcialidades, pagos en efectivo, facturas en dólares)?
4. ¿Qué pasó la última vez que se equivocó en una deducción o en un tipo de cambio y cuánto le costó?
5. Si una herramienta le diera el total deducible ya auditado y un pronóstico del tipo de cambio, ¿cómo la usaría y cuánto estaría dispuesto a pagar por ella?

**Respuestas:** pendiente.

**Aprendizajes:** pendiente.

## 3. Las 3 preguntas analíticas

| Etapa | Pregunta | Detalle |
|---|---|---|
| E1 Pronóstico | ¿Cuál será el tipo de cambio FIX USD/MXN promedio mensual en los próximos 6 meses? | Variable a pronosticar: tipo de cambio FIX mensual (Banxico, serie SF43718, desde 2010; datos diarios agregados a meses, 36+ periodos). Series de apoyo: INPC y TIIE |
| E2 Experimentos | ¿Qué parámetros fiscales cambian de forma significativa el total deducible de un lote de CFDI? | Variable respuesta: Total Deducible en MXN calculado por el sistema. Factores con 2 niveles cada uno: `modo_tipo_cambio` (actual / fecha del CFDI), `notas_credito` (excluir / restar), `iva_por_defecto` (0 / 0.16) y `tope_efectivo` ($2,000 / sin tope). Diseño factorial sobre lotes de CFDI de prueba |
| E3 Multivariado | ¿Qué tipos de contribuyente se parecen en su comportamiento fiscal? | Grupos a comparar: perfiles por giro (por ejemplo servicios profesionales, comercio, hospedaje). Variables a la vez: porcentaje deducible, porcentaje de facturas PPD pendientes, porcentaje rechazado por lista de no deducibles, porcentaje pagado en efectivo, IVA acreditable e ingresos facturados |

Los lotes de E2 y E3 usan datos de prueba o anonimizados: sin RFC reales, nombres ni razones sociales de terceros.

### 3.1 Hipótesis, método y criterio de éxito

* **E1:** se espera una tendencia con rezago respecto a la inflación y a las tasas. Se compararán un modelo ingenuo, Holt-Winters y SARIMA con los últimos 6 a 8 periodos como prueba; el éxito es un MAPE menor que el del modelo ingenuo y un pronóstico con intervalo de confianza.
* **E2:** se espera que el tipo de cambio usado y el tratamiento de notas de crédito tengan efecto significativo en el total deducible, y el IVA por defecto uno menor. Se analizará un diseño factorial con ANOVA (verificando normalidad y varianzas) al 5 % de significancia.
* **E3:** se espera que los perfiles por giro formen pocos grupos (por ejemplo, alto contra bajo porcentaje de pagos en efectivo). Se estandarizarán las variables, se aplicará PCA y k-medias o clúster jerárquico, eligiendo el número de grupos con el codo y la silueta.

## 4. Plan de recopilación de datos

| # | Fuente | Qué se descarga | Frecuencia | Método |
|---|---|---|---|---|
| 1 | Banxico, Sistema de Información Económica (API) | Tipo de cambio FIX (SF43718, diario), INPC general (SP1, mensual), TIIE a 28 días y valor de las UDIS. Todas desde 2010. Los IDs de TIIE y UDIS están por confirmar en el catálogo SIE | Semanal por Actions | API oficial con token gratuito |
| 2 | INEGI, Banco de Indicadores (API) | INPC general mensual (indicador por confirmar en el BIE), para contrastar con el de Banxico | Semanal por Actions | API oficial con token gratuito |

Por qué estas series: el sistema ya convierte CFDI en dólares y avisa que, para declarar, el tipo de cambio debe ser el publicado en el DOF (Art. 20 del CFF). El FIX de Banxico es la base de ese valor. Pronosticarlo ayuda a decidir cuándo cobrar o facturar en divisas. La inflación y las tasas explican su movimiento.

### Análisis ético y legal

| Fuente | robots.txt (url y fecha de revisión) | Términos de uso | Conclusión |
|---|---|---|---|
| Banxico SIE | https://www.banxico.org.mx/robots.txt — revisado el 8-nov-2026. Solo prohíbe `/dyn`, `/dyn/` y `/ALEPH`; la ruta `/SieAPIRest` no está vetada. | https://www.banxico.org.mx/footer-es/salvedad-politicas-uso-banco-.html — Banxico autoriza de forma general usar y reproducir su información, a condición de citar la fuente y la dirección de internet; no asume responsabilidad por el uso de terceros ni autoriza revender sus datos como propios. | Se usa la API oficial con token propio, 1 consulta por serie, con pausa de 2 s |
| INEGI BIE | https://www.inegi.org.mx/robots.txt — revisado el 8-nov-2026. Permite `/app` (donde vive la API); solo prohíbe rutas de catálogo y descarga del RNM, que no usamos. | https://www.inegi.org.mx/inegi/terminos.html — Permite copiar, adaptar y explotar la información conservando metadatos; hay que citar "Fuente: INEGI, [producto]", avisar si se hizo análisis o transformación y no sugerir aval del INEGI. | Se usa la API oficial con token propio, con pausa de 2 s |

Reglas que seguimos: identificarnos con User-Agent, no pasar de 1 solicitud cada 2 segundos, no tocar datos personales, citar la fuente y guardar los datos crudos sin modificar. Los comprobantes fiscales de personas reales no se suben al repositorio.

Aviso: el tipo de cambio de mercado que usa el sistema por defecto no es el publicado en el DOF. Este observatorio lo usa para análisis y pronóstico, no como valor fiscal para una declaración.

## 5. Arquitectura de datos

```
APIs ──▶ Bronce (crudo) ──▶ Plata (validado) ──▶ Oro (análisis)
```

* **Bronce (E0, en operación):** la respuesta de cada API tal como llegó, con fecha y hash SHA-256 en `manifiesto.csv`; nunca se modifica. Series: tipo de cambio FIX, INPC, TIIE a 28 días y UDIS (Banxico), más el INPC de INEGI cuando exista `INEGI_TOKEN`. Se capturan cada lunes con GitHub Actions y se revisan con `src/verificar_bronce.py`.
* **Plata (E1):** series limpias, con fechas y valores numéricos, sin duplicados; el tipo de cambio diario se agrega a promedio mensual. Una puerta de calidad rechaza capturas incompletas.
* **Oro (E3):** tablas listas para cada pregunta: la serie mensual para E1, la tabla factorial de lotes de CFDI para E2 y la matriz perfil × variable para E3.

## 6. Riesgos principales

* **Un ID de serie incorrecto o vacío.** El extractor avisa si una serie viene vacía y el workflow termina en error. Los IDs de INEGI siguen por confirmar en el BIE.
* **La API cambia de formato o se cae.** El crudo se guarda tal cual y la limpieza vive en Plata, así que un cambio no destruye lo capturado.
* **Uso fiscal indebido.** El tipo de cambio de mercado no sustituye al publicado en el DOF; se aclara en la propuesta y en el sistema.
* **La entrevista no confirma la pregunta detonadora.** Se ajustarán la pregunta y los factores de E2 antes de iniciar E1.
