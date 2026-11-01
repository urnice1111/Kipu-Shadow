# Kipu Shadow

Anonimización del corpus de Kipu Pay (chats de Slack, documentos PDF/HTML/MD y tablas CSV/XML) sin filtrar datos personales y sin romper la utilidad ni las relaciones entre fuentes. Pipeline propio por reglas: sin LLM y sin servicios ni librerías de anonimización.

Reto: "Vende los datos sin vender a la gente" (Frontier). Enunciado completo en `ENUNCIADO.md`; decisiones de diseño en `DECISIONS.md`.

## Resultados

| Corrida | Tests ocultos | Puntaje |
|---|---|---|
| 1 | 60 % del set | 95 / 125 |
| 2 | 75 % del set | 146 / 156 |
| 3 | 100 % del set | 193 / 205 |

Todas las corridas son posteriores a la migración de Págalo: 10.856 registros (2.999 chats, 34 documentos, 7.823 filas). Un `/run` completo tarda unos 42 s y usa 0 tokens.

## Cómo funciona

1. **Ingesta 1:1** desde el API de fuentes. Descubre canales, documentos y tablas en cada corrida, y la salida tiene que coincidir con `record_index` o no se publica.
2. **Directorio de personas.** Une clientes, empleados, perfiles de Slack y PQR solo con evidencia fuerte (correo, cédula, celular, ids). Un nombre igual nunca junta a dos personas.
3. **Seudónimos persistentes** en SQLite con un secreto local: mismo género, mismo formato de correo, cédula del mismo largo, celular válido. No cambian entre corridas ni cuando crecen las fuentes.
4. **Reemplazo por fragmentos.** Correos (también deletreados), direcciones, fechas de nacimiento (también en prosa), cédulas, celulares, cuentas, placas, handles, nombres e iniciales. El resto del texto queda byte a byte.
5. **Homónimos.** Se resuelven con el dato más cercano a la mención: cédula o sus últimos dígitos, radicado, crédito, placa, transacción, ocupación; luego el rol ("te atiende X, agente…") y el contexto del hilo.
6. **Cuasi-identificadores.** Si ocupación, barrio y año quedan juntos, la ocupación pasa a sector, el barrio a ciudad y el año a "hace unos años". Aplica en tablas, notas, chats y documentos completos.
7. **Auditor** con la misma normalización de `validar.mjs` (tildes, confusables, invisibles, separadores entre dígitos). Si queda una forma real, la reemplaza antes de publicar.
8. **`/anonymize` en vivo** con el mismo motor y registro: una persona ya vista recibe exactamente su seudónimo publicado.

## Requisitos

- macOS o Linux con Python 3.12 o más nuevo
- Node 20 o más nuevo (solo para `validar.mjs`)
- ngrok (solo para exponer el servicio)

## Configuración

Crea `.env` en la raíz con los datos de `/evento/reto` en Frontier:

```
SOURCES_URL=https://...
SOURCES_TOKEN=...
```

`.env`, `data/`, `output/`, `logs/`, `fuentes/` y `sample/` están en `.gitignore`: tienen datos reales.

## Uso

Levantar la API en `http://localhost:9000/v1`. Crea `.venv` e instala dependencias si hace falta:

```bash
./run.sh
```

Exponerla en internet con ngrok y caffeinate. Imprime la URL para Frontier:

```bash
./scripts/serve_public.sh
```

Endpoints (contrato en `api/participante.openapi.yaml`):

| Ruta | Qué hace |
|---|---|
| `GET /v1/health` | estado del servicio |
| `POST /v1/run` | regenera la salida desde el API de fuentes, en segundo plano |
| `GET /v1/run/{job_id}` | estado de la corrida |
| `GET /v1/output/{archivo}` | `chats.jsonl`, `docs.jsonl`, `tables.jsonl`, `entities.json` |
| `GET /v1/entities` | diccionario de entidades (solo para el jurado) |
| `POST /v1/anonymize` | anonimiza registros nuevos en vivo |

## Pruebas locales (no gastan corridas)

```bash
.venv/bin/pytest -q                                   # tests unitarios y de contrato
.venv/bin/python scripts/score_local.py sample        # muestra: 13/13 + validar.mjs
.venv/bin/python scripts/score_local.py corpus        # corpus real: 5/5 públicos + validar.mjs + auditor
.venv/bin/python scripts/score_local.py corpus --refresh   # vuelve a bajar el corpus
```

Diagnóstico (imprimen datos reales, úsalos solo en local):

| Script | Qué mide |
|---|---|
| `scripts/probes.py` | consistencia, homónimos, tripletas, fugas, campos sin revisar |
| `scripts/homonyms.py` | cada mención de un homónimo y a quién se asignó |
| `scripts/leftover_names.py` | nombres que quedaron iguales en la salida |
| `scripts/requests_report.py` | qué mandó el evaluador y qué respondimos (`logs/requests.jsonl`) |
| `scripts/replay_anonymize.py` | reproduce las llamadas del evaluador contra el código actual |

## Operación

- `./scripts/backup_registry.sh <etiqueta>`: respalda el registro de seudónimos y su secreto. Perderlos cambia todos los seudónimos publicados.
- `logs/requests.jsonl`: cada petición con cuerpo, respuesta, estado y latencia. El token sale como `***`.
- `logs/runs/<fecha>_<job>/`: copia de cada salida publicada y del resumen del auditor.

## Estructura

```
app/
  main.py          API (FastAPI)
  jobs.py          corridas en segundo plano
  pipeline.py      ingesta → motor → auditor → publicación
  live.py          /anonymize en vivo
  requestlog.py    log de peticiones
  ingestion/       cliente del API de fuentes y parsers (Slack, PDF, HTML, MD, CSV, XML)
  core/
    identities.py  directorio de personas y evidencia
    registry.py    seudónimos persistentes
    detect.py      detectores (correos, números, fechas, nombres…)
    engine.py      resolución y reemplazo
    anonymize.py   aplicación por fuente
    entities.py    entities.json
    audit.py       auditor con la normalización del juez
    text.py        normalización
scripts/           servicio público, respaldos, puntaje local y diagnóstico
tests/             tests unitarios, de contrato y de mecanismos
```


