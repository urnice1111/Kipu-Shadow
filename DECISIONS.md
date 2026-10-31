# Decisiones de Kipu Shadow

Documento vivo. Responde las tres preguntas del reto (qué es PII, qué se conserva a propósito y cuánto cuesta correr) a medida que cada parte del pipeline existe. Lo que todavía no está implementado se marca como tal.

## Estado

| Etapa | Estado |
|---|---|
| API `/v1` (contrato) | Hecha (Hito 1) |
| Ingesta y normalización 1:1 | Hecha (Hito 2) |
| Detección de PII, identidades, seudónimos, auditoría | Pendiente (Hitos 3-6) |

Hasta que la anonimización exista, `POST /run` ingiere y verifica ids, pero termina en `failed` y no publica nada en `/output`.

## Normalización de las fuentes

El contrato fija los campos de salida, pero no cómo se derivan algunos de ellos de la entrada cruda. Estas son las reglas elegidas.

### Chats
- `id` es el `client_msg_id`.
- `thread_id` es `<canal>:<thread_ts>`; el mensaje raíz de un hilo no trae `thread_ts`, así que usa su propio `ts`. Coincide con la muestra.
- `author` es `username` en mensajes del bot (`Kipi`). Para el resto: `real_name`, luego `profile.real_name`, `profile.display_name` y `name`. Nunca el uid.
- `attachments` lleva un `{filename}` por archivo con su `name`, en el mismo número que en la entrada.
- Las menciones `<@UID>` se convierten en `@Nombre` del usuario, para que en la etapa de seudónimos se traten como cualquier otro nombre. Si el uid no existe en `users.json` se deja tal cual.
- `reactions`, `edited` y demás campos de Slack no están en el esquema de salida y no se copian.

### Documentos
- **Markdown**: `body` es el archivo tal cual, con front matter. `metadata` son las claves del front matter, con valor de texto; las listas YAML (`- item` o `[a, b]`) se unen con `, `. `title` es el `title` del front matter, si no el primer `#`.
- **HTML**: `body` es Markdown propio generado con BeautifulSoup (encabezados, párrafos, listas, tablas) que conserva los comentarios `<!-- -->` donde estaban; `<style>` y `<script>` se omiten. `metadata` es cada `<meta name>` con su `content`. `title` es `<title>`.
- **PDF**: texto de cada página con PyMuPDF. `metadata` son las claves no vacías del diccionario de información del PDF (`title`, `author`, `subject`, `keywords`, `creator`, `creationDate`, y `producer`/`modDate` si existen). `title` es el del PDF, si no la primera línea.

### Tablas
- El charset y el separador salen de `GET /tables`, no del código.
- Todas las columnas se conservan y todos los valores son texto.
- XML: una fila por hijo de la raíz; atributos por su nombre y elementos hijos por su tag. Un atributo de un hijo se llama `<tag>_<attr>` (por ejemplo `documento_tipo` en `empleados.xml`). Los comentarios del XML, como el de quién exportó `pqrs.xml`, no pertenecen a ninguna fila y no salen.
- La llave de cada tabla es la columna cuyos valores son únicos y coinciden con los ids de `record_index` (`cliente_id`, `tx_id`, `radicado`, `id`).

## Garantías de la ingesta
- Cada corrida descubre canales, fechas, documentos y tablas desde el API; no hay listas fijas, para que el crecimiento de las fuentes entre sin cambios de código.
- La salida debe coincidir uno a uno con `record_index`: si falta, sobra o se repite un id, la corrida falla antes de escribir.
- El token sólo vive en memoria del cliente HTTP; no se escribe en disco, logs ni mensajes de error.
- Cliente con reintentos (429, 5xx, errores de red, respetando `Retry-After`) y un tope de 8 peticiones por segundo, por debajo del límite de 600 por minuto.

## Costo medido

| Corrida | Registros | Tiempo | Peticiones | Tokens LLM |
|---|---|---|---|---|
| Ingesta del corpus inicial (31 oct 2026) | 2.028 chats, 26 docs, 6.243 filas | 24 s | 183 | 0 |

## Pendiente de definir
- Alcance de PII, entidades conservadas (organizaciones, lugares, marcas, figuras públicas) y regla de cuasi-identificadores: Hitos 3-6.
