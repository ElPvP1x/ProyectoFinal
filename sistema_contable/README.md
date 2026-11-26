# Sistema Contable — Auditor de CFDI 4.0

Sistema web local que lee **descargas masivas del SAT sin trabajar** (Excel crudo),
las clasifica por tipo de archivo, convierte todo a pesos y entrega los montos
auditados más un Excel depurado listo para revisar.

## Arranque rápido (Windows)

Doble clic en `iniciar.bat` (crea el entorno virtual, instala dependencias y abre el navegador).

Manual:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abre http://127.0.0.1:5000

También funciona por consola:

```bat
python procesador_cfdi.py "Emitidas Agosto.xlsx" "Recibidas Agosto.xlsx" "Pagos Agosto.xlsx"
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `procesador_cfdi.py` | Motor: lectura inteligente, alias de columnas, análisis de color, reglas por tipo de archivo, exportación |
| `lector_xml.py` | Lee CFDI en su XML original (3.3 / 4.0), `.zip` de la descarga masiva y carpetas |
| `tipo_cambio.py` | Conversión de divisas a MXN con caché en disco y respaldo sin internet |
| `app.py` | Servidor Flask (`/procesar`, `/descargar/<id>`, `/config`, `/limpiar`) |
| `templates/index.html` | Dashboard: KPIs, tarjeta por archivo, tabla con totales al pie |
| `config_reglas.json` | **Toda la parametrización fiscal, sin tocar código** |

## Dos fuentes: Excel o XML

**Excel / CSV** del portal contable — el camino original. Mapea columnas por alias
y deduce lo que puede.

**XML del SAT** — `.xml` sueltos, el `.zip` de la descarga masiva (incluso anidado)
o una carpeta. Es la fuente buena, porque el XML trae:

* el tipo de comprobante declarado (no hay que adivinar por texto ni por color);
* cada impuesto desglosado (IVA, IEPS, IVA e ISR retenidos);
* la **`ClaveProdServ`** del catálogo del SAT de cada concepto, que identifica el
  giro sin depender de cómo esté redactada la descripción;
* el **tipo de cambio que el emisor declaró**, que manda sobre cualquier consulta
  de mercado;
* en los complementos de pago, el **UUID de la factura que se está pagando**.

Si el ZIP trae el archivo de **metadata** del SAT, se usa para confirmar qué CFDI
fueron cancelados — dato que el XML por sí solo no tiene.

Emitidas y Recibidas se deciden por el RFC del contribuyente, deducido de la tanda
completa (el RFC que aparece en todos los comprobantes). Si no se puede confirmar,
el sistema avisa; captura `rfc_contribuyente` en la configuración para fijarlo.

## Los 5 archivos que puede recibir

Sube los que tengas; no hacen falta los cinco. El sistema deduce qué es cada uno
**por el nombre del archivo** y, si el nombre no lo dice, por el tipo de comprobante
que domina adentro (lo avisa en el diagnóstico). Puedes forzarlo con
`origen_por_archivo` en la configuración.

| Archivo | Qué suma | Qué deja fuera |
|---|---|---|
| **Emitidas** | PUE + REP emitidos | Notas de crédito, PPD sin REP, cancelados |
| **Recibidas** | Gastos PUE + REP recibidos | Notas de crédito, PPD sin REP, efectivo > tope, lista negra, cancelados |
| **Egresos** | Igual que Recibidas | Igual que Recibidas |
| **Pagos** | Todos los pagos, desglosados por forma de pago | Efectivo por arriba del tope, cancelados |
| **Nóminas** | Percepciones + otros pagos (el gasto del patrón) | Cancelados |

`Total Deducible = Recibidas + Egresos + Nóminas + REP de Pagos`
Los **ingresos facturados** (Emitidas) van aparte: no son una deducción.

No hay doble conteo: una factura PPD nunca suma, así que su REP es lo único
que entra, ni antes ni después.

## Reglas

1. **Notas de crédito** — si el tipo dice `NotaCredito`, `Nota de Crédito` o `E`,
   el CFDI **se informa pero no entra en la sumatoria**, en cualquiera de los cinco
   archivos. Con `"notas_credito": "restar"` vuelve al comportamiento de restarlas.
2. **PPD** — una factura timbrada en parcialidades no suma: acumula o deduce
   cuando llega su REP. No se marca como rechazo, se marca como pendiente.
3. **Tope de efectivo** — forma de pago `01` por `>= tope_efectivo` ($2,000) no es
   deducible (Art. 27 F-III LISR). **No** se aplica a nómina (los salarios en
   efectivo sí deducen si se timbra el CFDI); cámbialo con
   `aplicar_tope_efectivo_a_nomina`.
4. **Conceptos no deducibles** — lista negra sobre la descripción, con coincidencia
   por palabra completa (`cine` no hace match con `cocina`), más frases y RFC exentos.
5. **Cancelados** — se rechazan antes de todo. `Cancelable sin aceptación` **no**
   cuenta como cancelado (es un CFDI vigente).
6. **Duplicados** — se eliminan por UUID *dentro del mismo tipo de archivo*, para no
   borrar una factura que legítimamente aparece en Emitidas y su REP en Pagos.

## Reglas de la investigacion de nov-2026 (`reglas_md.py`)

Salen del documento «Lo que el contador revisa, descarta y corrige a mano en las
facturas de sus clientes». Todas se ajustan en `config_reglas.json`.

| Regla | Que hace | Config |
|---|---|---|
| **7** RFC generico / otro receptor / uso S01 | Rechaza facturas a `XAXX010101000`, a nombre de otro RFC (solo si se sabe con certeza quien es el contribuyente) o con uso S01 (CFF 29-A) | `rechazar_rfc_generico` |
| **8** Lista 69-B | Rechaza proveedores en la lista **definitiva**; los presuntos solo dan alerta (CFF 69-B) | `archivo_69b` (`lista_69b.csv` del SAT), `rfc_69b_definitivos` |
| **9** Otro ejercicio | Rechaza CFDI de un anio distinto (LISR 27-XVIII) | `ejercicio_fiscal` |
| **Inversion** | Uso I01-I08: no suma al gasto del mes (se deprecia, LISR 34), muestra la tasa anual y **conserva su IVA acreditable**. Intereses, seguros y mantenimiento no cuentan como inversion | `separar_inversiones`, `palabras_no_inversion` |
| **Sustitucion** | Si un CFDI vigente lo reemplaza con relacion 04, la original no suma (solo XML) | — |
| **Restaurante** | Solo el **8.5 %** con tarjeta o monedero (04, 05, 28, 29); en efectivo, nada; bares nunca (LISR 28-XX). El IVA acreditable va en la misma proporcion | `restaurantes` |
| **IVA acreditable por fila** | Columna nueva `IVA Acreditable`: sigue a lo que se deduce; una nota de credito en modo `restar` lo reduce (LIVA 7) | `notas_credito` |
| **Tope de automovil** | Una compra con uso I03 que pasa $175,000 ($250,000 electrico o hibrido) avisa en el motivo que solo se deprecia esa proporcion (LISR 36-II) | `tope_auto`, `tope_auto_electrico` |
| **PPD y REP** | Une cada factura PPD con su complemento de pago por UUID; la que no tiene REP en la tanda avisa que su IVA no es acreditable (LIVA 5-III) | — |
| **Anticipos y lentes** | Alerta en CFDI con relacion 07 o forma 30 (no deducir dos veces) y en lentes con uso D0* (tope $2,500 por persona) | `tope_lentes` |
| **Tope global de deducciones personales** | Resumen del Excel: monto detectado contra 5 UMA anuales y 15 % de los ingresos (LISR 151) | `uma_diaria`, `ingresos_anuales` |
| **Alertas** (columna `Alertas`, no cambian la suma) | Nota de credito sin relacion; descripcion generica; PUE con forma 99; PPD con forma distinta de 99; posible falta de retencion (persona moral a persona fisica 612/606/626); ISR o IVA retenido mal calculado; CP o regimen del receptor distinto a la constancia | `alertas`, `cp_contribuyente`, `regimen_contribuyente` |

Cambio de comportamiento: `hotel` salio de la lista negra (el hospedaje en Mexico se
deduce sin tope si el viaje es del negocio); `spa`, `masaje` y `crucero` siguen fuera.

**Lo que sigue necesitando criterio humano** (el documento tambien lo dice): si el gasto es
estrictamente indispensable o personal, la materialidad de la operacion, los 50 km de los
viaticos, el uso personal de autos y celulares, y el prorrateo de IVA con actividades exentas.

**Lo del documento que aun no esta en el sistema:** topes de viaticos ($750 / $1,500 / $850 /
$3,850, necesitan los dias y el contexto de hospedaje o transporte), el numero de permiso del
complemento de combustible y la consulta de estatus al SAT en linea. El tope global de
deducciones personales no separa retiro ni discapacidad (el CFDI no lo dice): restalos a mano.

## Tipos de comprobante escritos con palabras

Muchos portales no ponen la clave del SAT sino el nombre. El sistema entiende
`Factura`, `NotaCredito`, `Nota de Crédito`, `Recibo de Nómina`, `Pago`,
`Complemento de pago`, `Egreso`, `Traslado` y los mapea a `I / E / N / P / T`.

## Divisas

Todo el dashboard trabaja en **MXN**. Un CFDI en USD, EUR, etc. se convierte y
conserva `Moneda Original`, `Total Original` y `Tipo de Cambio` para que la
conversión sea auditable.

```json
"convertir_a_mxn": true,
"modo_tipo_cambio": "actual",      // "actual" = tasa de hoy · "fecha" = la del día de cada CFDI
"tipos_cambio_fijos": {}           // { "USD": 18.3456 } manda sobre todo lo demás
```

> **Aviso fiscal:** las tasas de las APIs (open.er-api.com, frankfurter.app) son de
> **mercado**, no el tipo de cambio **DOF** que exige el Art. 20 del CFF. Para
> declarar, captura el DOF en `tipos_cambio_fijos`. El dashboard siempre dice qué
> fuente usó. Sin internet toma la última tasa de `tipo_cambio_cache.json`.

## Montos que analiza

Subtotal · Descuento · IVA trasladado · IEPS · IVA retenido · ISR retenido ·
Total retenciones · Percepciones · Deducciones · Otros pagos · Total ·
Monto pagado · **Importe que suma al total**.

Lo que el archivo no traiga se reconstruye con la fórmula del CFDI
(`Total = Subtotal − Descuento + Traslados − Retenciones`). Si un CFDI no trae
**ni subtotal ni impuestos**, el sistema no inventa el desglose: marca la fila como
incompleta y lo dice en el dashboard. Con `"iva_por_defecto": 0.16` lo separa
asumiendo esa tasa.

## Análisis de color ("ojos de contador")

Cuando el portal no llena *Tipo de Comprobante* pero pinta la fila de rojo, se leen
fuente y relleno de las columnas clave y se infiere una nota de crédito. Si la fila
está en rojo pero **sí** declara tipo `I`, no se toca el importe: aparece en la
pestaña **Revisar color**.

## El Excel depurado

Una hoja por archivo cargado, más:

* **Resumen General** — gran total, tipo de cambio aplicado y un bloque por archivo.
* **Notas de Crédito** — todas las que quedaron fuera de la suma.
* **No Sumados** — notas de crédito, PPD sin REP y rechazados.
* **Detalle Completo** — todos los CFDI con todas las columnas.

Cada hoja trae al pie una fila **TOTAL** por moneda, fuera del autofiltro; las filas
que no suman van en gris; y las columnas de importe que van en ceros no se imprimen,
para que la hoja quede corta y legible.

## Pendientes conocidos

* **El análisis de color se desalinea** cuando el Excel trae filas vacías o pies de
  página en medio: los colores se leen por fila física y el DataFrame descarta esas
  filas. Afecta solo a los archivos que marcan notas de crédito con color.
* Color: falta soportar colores de **tema** de Excel (`theme`+`tint`), que openpyxl
  no resuelve a RGB, y decidir si naranja o gris significan algo en tu portal.
  Hoy el naranja de relleno se lee como rojo.
* Regla 4: falta afinar la lista negra por giro del contribuyente (peaje y viáticos).
  `hotel` ya no está en la lista negra desde nov-2026.
* El combustible pagado en efectivo ya se rechaza sin importar el monto
  (`combustible_solo_medios_bancarios`); falta leer el número de permiso del complemento.
