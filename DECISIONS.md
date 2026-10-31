# Decisiones de Kipu Shadow

Responde las tres preguntas del reto: qué consideramos PII, qué conservamos a propósito y cuánto cuesta correr el pipeline. Pipeline propio por reglas: sin LLM, sin servicios ni librerías de anonimización.

## Cómo funciona

1. **Ingesta 1:1** desde el API de fuentes (chats Slack, PDF/HTML/MD, CSV/XML). Cada corrida descubre canales, fechas, documentos y tablas; la salida debe coincidir exactamente con `record_index` o la corrida falla antes de publicar.
2. **Directorio de identidades.** Una persona por fila de `clientes` y de `empleados`; los perfiles de Slack se enlazan por correo o celular, luego por nombre único, luego por evidencia del hilo (cédula, celular, correo, `cliente_id` o radicado que aparecen donde escribe ese usuario) y por descarte entre homónimos. **Un nombre igual nunca fusiona a dos personas.**
3. **Motor de reemplazo por spans.** Se reemplazan solo los fragmentos personales, en este orden de prioridad: correos (también deletreados con "arroba"/"punto"), direcciones, pasaportes, fechas de nacimiento conocidas, cédulas y celulares (con cualquier separador o `+57`), números de cuenta/crédito/póliza, placas, handles, nombres. El resto del texto queda byte a byte.
4. **Resolución por contexto.** Un nombre que corresponde a varias personas (homónimos, agente que se llama como una clienta) se decide así, en orden: el identificador más cercano a la mención en su fila o párrafo (radicado, `cliente_id`, cédula o sus últimos dígitos, número de crédito o solicitud, placa, y una fecha de transacción si el texto también da su monto o su concepto); el rol pegado al nombre ("te atiende X", "X, agente de…"); y por último el autor, las menciones y los identificadores del hilo. El mismo nombre dos veces en una frase nombra a dos personas. Ciudad y cargo nunca desempatan. Un nombre de pila suelto se reemplaza si su dueño está en contexto (también en minúscula, salvo nombres que son palabras comunes como "rosa" o "julio" sin saludo delante) o, en documentos y canales internos, si un solo empleado se llama así.
5. **Seudónimos persistentes** en SQLite (`data/pseudonyms.db`) con un secreto local: nombre del mismo género, correo con el mismo patrón y tipo de dominio, cédula del mismo largo, celular colombiano válido, dirección y fecha con formato real, lejos del original. Las personas se encuentran por cualquiera de sus llaves (fila, uid de Slack, HMAC de correo o cédula) y los identificadores se indexan por su valor original, así que **nada cambia entre corridas ni cuando crecen las fuentes**.
6. **Auditor.** Busca cada forma original declarada en toda la salida con la misma normalización del juez (tildes, confusables, separadores entre dígitos). Si encuentra algo, hace un reemplazo de último recurso y vuelve a auditar.
7. **`/anonymize`** usa el mismo directorio y registro de la última corrida: una persona ya vista recibe exactamente el mismo seudónimo; una nueva recibe uno nuevo y único.

## Qué consideramos PII

- **Identificadores directos:** nombres completos y parciales (incluidos MAYÚSCULAS sin tildes, nombres partidos entre líneas de PDF, inicial y apellido como "M. Jiménez" y tokens en nombres de archivo como `extracto_camila_restrepo.pdf`), correos (escritos y deletreados), cédulas, celulares, direcciones, fechas de nacimiento (también en prosa: "18 de octubre de 1983"), pasaportes, placas, números de cuenta, crédito y póliza, handles de Slack, de sistema (`fernanda.vargas`) y de redes armados con el nombre (`@arojas`).
- **Dónde:** texto de chat, autor, menciones `<@UID>`, nombres de adjuntos, título, cuerpo, front matter, comentarios HTML, metadatos de PDF y HTML, nombre del documento, y todas las celdas de las tablas.
- **Cuasi-identificadores:** ocupación + barrio/ciudad + año. En `clientes` la ocupación siempre pasa a sector ("fotógrafa" → "profesional de las industrias creativas") y el barrio a otro barrio de la misma ciudad; en el texto libre donde una ocupación aparece junto a un lugar o un año, la ocupación pasa a sector, el barrio a su ciudad y el año a "hace unos años". Las `notas` de `clientes` y los documentos completos cuentan como un solo registro, porque la fila ya tiene ciudad y fecha de vinculación y el jurado lee el documento entero. Es la misma regla en tablas y texto, para que la combinación no se pueda reconstruir uniendo fuentes.

## Qué conservamos a propósito

- **Organizaciones, marcas, lugares y figuras públicas**: bancos y billeteras (Bancolombia, Nequi, Davivienda, Banco de Occidente, Santander), comercios (Carulla, Éxito, Rappi, Juan Valdez), entidades (Superfinanciera, SIC, DIAN), ciudades, Plaza Botero, y figuras públicas (Shakira, Gabriel García Márquez, Jorge Isaacs...). Se declaran en `entities.json` con `kept: true`. Un apellido que es lugar ("Luis Santander") se reemplaza cuando nombra a una persona; "Santander" solo, como banco o departamento, se conserva.
- **Hechos de negocio**: montos, fechas de transacciones, estados, canales, el problema y la secuencia de cada conversación.
- **Llaves técnicas** (`cliente_id`, `tx_id`, radicados, `KP-xxx`, ids de mensaje y de hilo), para que las tablas sigan uniendo las mismas filas y cada persona conserve su número de registros. La relación "reporta a" usa el seudónimo del jefe.
- **Ciudad y fecha de vinculación** en `clientes`, igual que la salida ideal de la muestra.
- **Cargos** de empleados ("Contadora", "Líder de Soporte"): no se generalizan, no identifican a un cliente.

## Normalización de las fuentes

- `thread_id` = `<canal>:<ts del mensaje raíz>`; `author` = nombre del perfil (o `Kipi` para el bot), nunca el uid; `<@UID>` se convierte en `@Nombre` y luego se seudonimiza.
- Markdown tal cual con front matter; HTML convertido a Markdown conservando comentarios; PDF a texto con PyMuPDF. `metadata` conserva exactamente las claves de origen.
- XML: atributos y elementos hijos como columnas; el atributo de un hijo es `<tag>_<attr>` (`documento_tipo`). Todos los valores son texto.

## Costo medido

| Corrida | Registros | Tiempo | Tokens LLM |
|---|---|---|---|
| `/run` completo, corpus inicial (31 oct 2026, local) | 2.028 chats, 26 docs, 6.243 filas | 30 s (24 s de ingesta, 183 peticiones) | 0 |
| `/anonymize`, lote de 50 mensajes reales | 50 | 0,02 s | 0 |

Calidad local antes de cualquier corrida oficial: 13/13 tests de la muestra, 5/5 tests públicos, `validar.mjs` OK, 0 fugas del auditor sobre 1.254 formas originales, y en una simulación de crecimiento con datos reales todas las personas viejas conservan sus seudónimos.

## Límites conocidos

- Un homónimo sin ningún identificador cerca ni en su hilo se asigna a la persona en contexto o, en textos internos, al empleado; un tercero que se llama igual que un cliente o empleado y no deja ningún dato propio queda con el seudónimo de ese cliente o empleado.
- Un nombre de pila suelto de un cliente que no está en contexto no se reemplaza.
- Si un seudónimo generado coincide después con un dato real que llega con el crecimiento, se regenera ese valor: preferimos un cambio de seudónimo a una fuga.
- `entities.json` contiene las formas originales: solo para el jurado, nunca forma parte del dataset vendido. Servirlo sin autenticación es un requisito del reto, no algo aceptable en producción.
- "Cero fugas" del auditor significa cero fugas de las formas que conocemos; no es una prueba de anonimato absoluto.
