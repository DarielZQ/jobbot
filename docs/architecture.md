# Arquitectura

JobBot es una aplicación de línea de comandos en Python con un panel web local. Corre completa en la computadora de cada usuario: no hay servidor ni servicios en la nube (ADR-019).

## Código y datos separados

| Qué | Dónde | ¿En el repositorio? |
| :--- | :--- | :--- |
| Código | `src/jobbot/` | Sí |
| Plantillas y presets | `src/jobbot/templates/` | Sí |
| Configuración, perfil, base de datos, informes, secretos | `JOBBOT_HOME` | **Nunca** |

`JOBBOT_HOME` es una variable de entorno. Si no está definida, se usa la carpeta visible `JobBot` dentro del directorio del usuario (`C:\Users\<Usuario>\JobBot` en Windows, `~/JobBot` en Linux y macOS). `jobbot/paths.py` calcula todas las rutas en cada llamada, así que un test o una segunda instancia pueden apuntar a otra carpeta.

```
JOBBOT_HOME/
├── .env                      JOBBOT_CONTACT_EMAIL y otros valores privados
├── config/
│   ├── settings.yaml         región, rutas, HTTP, panel, notificaciones, CV, fuentes desactivadas
│   ├── search.yaml           familias de roles y filtros duros
│   └── targets.yaml          fuentes a consultar
├── profile/
│   ├── facts.yaml            hechos verificables del usuario
│   ├── answers.yaml          respuestas a preguntas típicas
│   ├── resumes/              it-support.yaml, data-ai.yaml, checks.yaml y los PDF generados
│   └── private/              contact.yaml, compensation.yaml,
│                             gmail_credentials.json, gmail_token.json
└── data/
    ├── jobbot.db             SQLite
    ├── reports/              <fecha>.html y latest.html
    ├── logs/                 daily-<fecha>.log, panel.log
    └── email_samples/        correos guardados por `alerts-sample` (temporal)
```

- Las rutas relativas de la configuración (por ejemplo `paths.db` o `email_alerts.token_file`) se resuelven dentro de `JOBBOT_HOME`.
- `cli.py` carga `JOBBOT_HOME/.env` al arrancar; una variable de entorno real con el mismo nombre tiene prioridad. `JOBBOT_HOME` solo puede venir del entorno real.
- Todo comando salvo `init` se detiene con un mensaje claro si la carpeta no tiene `config/search.yaml`.

## Plantillas y presets

`jobbot init --preset <nombre>` (`jobbot/initialize.py`) copia a `JOBBOT_HOME` las plantillas del paquete y nunca sobrescribe un archivo existente. El preset por defecto es `costa-rica-it`.

```
src/jobbot/templates/
├── presets/
│   ├── costa-rica-it/        settings.yaml, search.yaml, targets.yaml    → config/
│   └── remote-latam/         settings.yaml, search.yaml, targets.yaml    → config/
├── profile/                                                               → profile/
│   ├── facts.yaml, answers.yaml
│   ├── resumes/              it-support.yaml, data-ai.yaml, checks.yaml
│   └── private/              contact.yaml, compensation.yaml
├── env                                                                    → .env
└── grill/
    ├── setup-profile.yaml    tema de entrevista (`jobbot grill setup-profile`)
    ├── countries.yaml        datos de `region` por país, para la entrevista
    └── skills.yaml           habilidades que revisa el detector de grill-me
```

- El perfil de las plantillas es un ejemplo ficticio ("Alex Ejemplo", "Acme Corp"); `init` lo recuerda al terminar.
- Los archivos de `grill/` no se copian: los lee el paquete.
- `remote-latam` trae `region` vacío; el usuario lo completa con `grill setup-profile` o a mano.

Cada preset trae su bloque `region` en `settings.yaml`:

```yaml
region:
  country: "Costa Rica"        # como lo escriben los sitios de empleo
  country_code: CRI            # ISO 3166-1 alfa-3
  country_slug: costa-rica     # forma para URLs (Jobicy)
  utc_offset: -6               # desfase estándar; muchas vacantes remotas filtran por zona horaria
  timezone: America/Costa_Rica # nombre IANA
```

`config.with_region` completa con esos valores los campos que una fuente no declara: país de Workday y Jibe, código de país de Amazon, palabra clave de SuccessFactors, `geo` de Jobicy, país y desfase de Himalayas. Un valor escrito en la entrada de la fuente siempre gana. Si después de eso falta el país, la fuente lanza `SourceNotConfigured` y se reporta como "sin configurar" en vez de adivinar.

## Flujo

```
JOBBOT_HOME/config/targets.yaml  (menos settings.yaml: disabled_sources)
          │
          ▼
discovery/<fuente>.py ──► core.models.Job
          │
          ▼
matching/rules.py      filtros duros de search.yaml; guarda el motivo de descarte
          │
          ▼
matching/dedupe.py     dedupe_key entre fuentes; aviso "Ya postulaste"
          │
          ▼
core/db.py             SQLite en JOBBOT_HOME/data/jobbot.db
          │
          ├──► daily.py      informe HTML + notificación de Windows
          ├──► panel/        interfaz local en 127.0.0.1
          └──► grill/        detectores → cola de la pestaña Decisiones
```

JobBot nunca envía postulaciones (ADR-019): el flujo termina en mostrar la vacante y el CV recomendado.

## Máquina de estados (`core/state.py`)

```
DISCOVERED ─┬─► SKIPPED                 (no pasa filtros o es duplicado; se guarda el motivo;
            │                            `jobbot rescreen` puede reabrirla si cambian los filtros)
            └─► SCORED ─► QUEUED ─► APPLYING ─┬─► SUBMITTED ─► CONFIRMED | REJECTED | INTERVIEW
                   └─► SKIPPED                ├─► NEEDS_INPUT ─► QUEUED
                                              ├─► BLOCKED_CHALLENGE ─► QUEUED
                                              ├─► FAILED ─► QUEUED
                                              └─► UNCERTAIN   (nunca se reintenta solo)
```

Estados en uso:

- **`DISCOVERED`** y **`SKIPPED`:** los asigna el descubrimiento según los filtros.
- **Postulación manual:** `SUBMITTED` con motivo `applied_manually`, desde `DISCOVERED`, `SCORED`, `QUEUED` o `SKIPPED`. Deshacer la devuelve a `DISCOVERED`.
- **Postulación confirmada por correo:** `SUBMITTED` con motivo `applied_by_email` (ADR-018).
- **Resultado:** `INTERVIEW` o `REJECTED`, con motivo `manual`. Cerrar una postulación desde la pestaña Decisiones también la pasa a `REJECTED`.
- **"No me interesa":** `SKIPPED` con motivo `not_interested`.
- **"Volver a pendientes":** `DISCOVERED` con motivo `reopened_manually`. No aplica a duplicados.

Reglas:

- `rescreen` no toca las vacantes con `not_interested` o `reopened_manually`: las decisiones del usuario no se revierten al cambiar filtros.
- `rescreen` no usa la red, así que una vacante que se reabre sin descripción se juzga solo por título y ubicación. La siguiente búsqueda que la vuelve a ver descarga su descripción una vez (si la fuente tiene `enrich`) y la filtra de nuevo. El informe la muestra como "descartada al ver su descripción".
- Los estados del envío automático (`SCORED`, `QUEUED`, `APPLYING`, `NEEDS_INPUT`, `BLOCKED_CHALLENGE`, `FAILED`, `UNCERTAIN`) siguen en el esquema por compatibilidad, pero JobBot no los usa porque no postula (ADR-019). `SCORED` podría usarse si se agrega una puntuación opcional.

## Módulos

| Módulo | Responsabilidad |
| :--- | :--- |
| `jobbot/cli.py` | Comandos `init`, `grill`, `discover`, `daily`, `panel`, `jobs`, `applied`, `report`, `stats`, `rescreen`, `resumes`, `gmail-login`, `alerts-sample`, `alerts-status`; carga de `.env` |
| `jobbot/paths.py` | Rutas dentro de `JOBBOT_HOME` |
| `jobbot/initialize.py` | `jobbot init`: copia las plantillas sin sobrescribir |
| `jobbot/config.py` | Carga y valida `config/*.yaml` con Pydantic; aplica `region` a las fuentes |
| `jobbot/templates/` | Presets, perfil de ejemplo, `env` y archivos de grill-me |
| `jobbot/grill/__init__.py` | Entrevistas por rondas (`grill <tema>`) |
| `jobbot/grill/apply.py` | Convierte respuestas en cambios a los YAML del usuario, conservando sus comentarios (`ruamel.yaml`) |
| `jobbot/grill/signals.py` | Detectores de la corrida diaria y respuestas de la pestaña Decisiones |
| `jobbot/core/models.py` | `Job` y tipos comunes |
| `jobbot/core/state.py` | Estados y transiciones válidas |
| `jobbot/core/db.py` | Esquema, migraciones, upsert idempotente, consultas |
| `jobbot/core/http.py` | Cliente HTTP con intervalo mínimo por host, `Retry-After`, reintentos y `User-Agent` honesto |
| `jobbot/discovery/base.py` | Interfaz `Source` (`fetch`, `enrich`, `min_hours_between_runs`) y `SourceNotConfigured` |
| `jobbot/discovery/workday.py` | JSON del sitio de empleo de Workday, filtrado por faceta de país |
| `jobbot/discovery/successfactors.py` | Feed RSS público de SAP SuccessFactors Career Site Builder |
| `jobbot/discovery/greenhouse.py`, `lever.py` | APIs públicas de Greenhouse y Lever |
| `jobbot/discovery/amazon.py`, `getonboard.py`, `remotive.py`, `jobicy.py`, `himalayas.py`, `recruitee.py`, `jibe.py` | APIs públicas de bolsas y sitios de empleo |
| `jobbot/discovery/elempleo.py` | Listado público de elempleo |
| `jobbot/discovery/email_alerts.py`, `jobbot/mail/gmail.py` | Alertas de LinkedIn, CompuTrabajo, Indeed y elempleo desde Gmail, solo lectura (extra `gmail`) |
| `jobbot/discovery/applications.py` | Confirmaciones de postulación desde Gmail (ADR-018) |
| `jobbot/discovery/pipeline.py` | Construye y ejecuta las fuentes, respeta `min_hours_between_runs`, `rescreen` sin red |
| `jobbot/matching/normalize.py` | Normalización de texto, empresa y título |
| `jobbot/matching/rules.py` | Familias de roles y filtros duros con motivo |
| `jobbot/matching/language.py` | Idioma del anuncio y CV recomendado por vacante |
| `jobbot/matching/dedupe.py` | `dedupe_key` y aviso "Ya postulaste" |
| `jobbot/daily.py` | Corrida diaria: todas las fuentes, detectores de grill-me, informe HTML y notificación de Windows |
| `jobbot/panel/` | Servidor en 127.0.0.1 + `index.html` sin frameworks |
| `jobbot/resumes/` | CV en PDF desde YAML (Jinja2 + Chromium, extra `resumes`) y revisión con `checks.yaml` |
| `scripts/windows/` | `run_daily.ps1`, `install_schedule.ps1` (tarea "JobBot - busqueda diaria") e `install_shortcut.ps1` (acceso directo "JobBot") |
| `scripts/run_daily.sh` | Corrida diaria para cron en Linux y macOS |
| `scripts/probe_workday.py` | Prueba la URL de un sitio Workday antes de agregarlo |
| `scripts/privacy_scan.py` | Escaneo de privacidad de los archivos versionados (y, con `--history`, del historial) |

Dependencias: `httpx`, `jinja2`, `pydantic`, `pyyaml` y `ruamel.yaml` en el núcleo; `google-auth-oauthlib` en el extra `gmail` y `playwright` en el extra `resumes`.

## grill-me

grill-me es la forma en que JobBot pregunta en vez de suponer. Es determinista: no usa ningún modelo de lenguaje.

### Entrevistas (`jobbot grill <tema>`)

Un tema es un archivo de `src/jobbot/templates/grill/` con la clave `questions`. Hoy existe `setup-profile`. Campos:

| Campo | Para qué |
| :--- | :--- |
| `topic`, `title`, `intro` | Nombre, título y texto inicial del tema |
| `questions[].id` | Identificador de la pregunta |
| `questions[].ask` | Texto de la pregunta |
| `questions[].options` o `text: true` | Opciones cortas (se eligen por letra) o respuesta libre |
| `questions[].optional` | Una respuesta libre puede quedar vacía |
| `questions[].other` | La opción que pide escribir una respuesta libre (p. ej. "Otro") |
| `questions[].recommended`, `reason` | Respuesta recomendada y su motivo; solo en preferencias, nunca en datos sobre el usuario |
| `questions[].depends_on` | Se pregunta en una ronda posterior, cuando esas preguntas tienen respuesta |
| `questions[].when` | Solo se pregunta si una respuesta previa fue esa |
| `questions[].apply` | Nombre de la función de `grill/apply.py` (`APPLIERS`) que convierte la respuesta en cambios |

Funcionamiento:

- Cada ronda son las preguntas cuyas dependencias ya tienen respuesta. Enter acepta la recomendada.
- `apply.plan` calcula los cambios sin escribir. La CLI los muestra y pregunta "¿Los guardo? [s/N]"; solo con `s` se guardan.
- `ruamel.yaml` conserva los comentarios y el formato de los YAML del usuario.
- `setup-profile` pregunta país (llena `region` desde `countries.yaml`), familias, nivel máximo, modalidad, zona local (solo si acepta presencial), idiomas, nombre, correo y teléfono.

### Detectores (después de cada `jobbot daily`)

`grill/signals.py` registra cada corrida de cada fuente (las omitidas o sin configurar no cuentan) y propone preguntas:

| Detector | Condición | Opciones | Efecto |
| :--- | :--- | :--- | :--- |
| Postulación sin novedades | `SUBMITTED` o `CONFIRMED` sin cambios durante 21 días | "Sí, cerrarla" (recomendada) / "Esperar más" | Cerrarla la pasa a `REJECTED` (Cerradas) |
| Fuente con fallas | Las últimas 3 corridas de la fuente terminaron en error | "Desactivarla" (recomendada) / "Seguir intentando" | La agrega a `settings.yaml: disabled_sources` |
| Habilidad frecuente | Una habilidad de `grill/skills.yaml` aparece en el 30 % o más, y en al menos 5, de las vacantes pendientes con descripción, y no aparece en `facts.yaml` ni en los CV | "Sí, la he usado en el trabajo" / "La estoy aprendiendo" / "No", sin recomendada | La agrega a `facts.yaml: skills.work` o `skills.self_study` |

- Como máximo 3 preguntas nuevas por día. Cada pregunta tiene una clave única y nunca se repite.
- Se responden en la pestaña Decisiones del panel o con `jobbot grill pendientes`. Cada opción dice qué hace y al responder se aplica solo eso.
- El informe diario dice cuántas decisiones hay pendientes.

## Esquema de datos

Tabla `jobs` (una fila por vacante y fuente):

| Columna | Notas |
| :--- | :--- |
| `id` | Clave primaria; es el `#` que muestran el panel y la CLI |
| `source`, `ats`, `ats_job_id` | `UNIQUE(ats, ats_job_id)`: volver a descubrir actualiza `last_seen_at`, no duplica |
| `company`, `title`, `location`, `url`, `remote`, `posted_at`, `description` | Datos de la vacante. `remote` = 100 % remoto; los híbridos son `0` |
| `dedupe_key` | Hash de empresa + título + ubicación normalizados; detecta la misma vacante en otra fuente |
| `status`, `status_reason` | Estado actual y motivo (p. ej. `title_excluded: senior`) |
| `role_family` | Familia de roles (`it_support`, `data_ai`); migración 2 |
| `first_seen_at`, `last_seen_at`, `updated_at` | UTC ISO-8601 |
| `posted_approx` | `posted_at` sale de una edad relativa (Workday) o de la fecha del correo de una alerta de LinkedIn; migración 4 (ADR-020) |
| `recommended` | Sugerida por LinkedIn fuera de las alertas guardadas: puede ser vieja; migración 4 |

Migración 3 (ADR-019):

| Tabla | Contenido |
| :--- | :--- |
| `decisions` | Preguntas de grill-me: `key` única, `kind`, `question`, `options` (JSON), `recommended`, `reason`, `status` (`pending` o `answered`), `answer`, `created_at`, `answered_at` |
| `source_runs` | Una fila por corrida de cada fuente: `source`, `ran_at`, `error` (vacío si salió bien) |

Las migraciones usan `PRAGMA user_version` (ADR-002).

## Detección de ATS por URL

| ATS | Patrón |
| :--- | :--- |
| Workday | `*.myworkdayjobs.com`, `*.myworkdaysite.com` |
| Greenhouse | `boards.greenhouse.io`, `job-boards.greenhouse.io` |
| Lever | `jobs.lever.co` |
| Ashby | `jobs.ashbyhq.com` |
| SuccessFactors | `*.successfactors.com`, `career*.sapsf.*` |
| SuccessFactors Career Site Builder | `/go/<nombre>/<id>/`, `/job/<título>/<id>/` (dominio propio de la empresa) |
| Jibe | `*.jibeapply.com` |
| Phenom | `/us/en/job/...`, IDs `phn-...` (dominio propio) |
| Taleo | `*.taleo.net` |
| Oracle Recruiting | `*.oraclecloud.com/hcmUI/CandidateExperience` |
| iCIMS | `*.icims.com` |
| Eightfold | `*.eightfold.ai` |

## Cortesía de red

`core/http.py`, usado por todas las fuentes:

- **Intervalo mínimo por host:** `settings.yaml: http.min_interval_s`, con excepciones en `http.host_min_interval_s` (por ejemplo, el `crawl-delay` que pide un sitio).
- **`Retry-After`:** se respeta en 429 y 503.
- **Reintentos:** con espera creciente y un máximo (`http.max_retries`) para fallos de conexión (DNS, conexión rechazada o sin respuesta), 502–504 y los 403 que Google usa para avisar de límite de uso. Cualquier otro 403 (un sitio que bloquea al bot, un permiso que falta) es definitivo: la fuente se detiene y lo reporta.
- **`User-Agent` honesto:** `JobBot/<versión> (job search tool; contact: <JOBBOT_CONTACT_EMAIL>)`. Sin correo configurado, se omite la parte de contacto.

## Seguridad del panel

- Escucha solo en `127.0.0.1` y exige su propio `Host` (protección contra DNS rebinding).
- Las acciones solo se aceptan como POST JSON desde su propio `Origin`; nunca envía cabeceras CORS.
- No carga nada de CDNs: la página y sus recursos salen del paquete.
- Los datos de las vacantes se insertan como texto, nunca como HTML.
- Solo sirve PDF de CV con nombre válido.
- Se apaga solo tras 10 minutos sin uso.

## Decisiones

El detalle de cada decisión está en [`decisions.md`](decisions.md).

| ADR | Decisión | Estado |
| :--- | :--- | :--- |
| 001 | Python + uv; Playwright solo para PDF | Vigente, actualizada por 019 |
| 002 | SQLite como estado | Vigente |
| 003 | Sin evasión anti-bot | Vigente |
| 004 | Adapters deterministas por fuente | Vigente para descubrimiento; envío reemplazado por 019 |
| 005 | LinkedIn, Indeed y Wellfound sin automatización | Vigente |
| 006 | Envío autónomo con umbral de confianza | Reemplazada por 019 |
| 007 | Prioridad de plataformas por valor × facilidad | Vigente |
| 008 | Documentación mínima | Vigente, actualizada por 019 |
| 009 | Familias de roles | Vigente |
| 010 | CV generados desde el perfil | Vigente, actualizada por 019 |
| 011 | Sitios que bloquean bots y APIs con límite de uso | Vigente |
| 012 | Alertas por correo con Gmail de solo lectura | Vigente |
| 013 | elempleo y Jibe directos; Indeed solo por correo | Vigente |
| 014 | Corrida diaria programada | Vigente, actualizada por 019 |
| 015 | CV recomendado por vacante y postulaciones manuales | Vigente |
| 016 | Panel local en el navegador | Vigente |
| 017 | Trabajo remoto: bolsas remotas y "100 % remoto" | Vigente |
| 018 | Postulaciones confirmadas por correo | Vigente |
| 019 | Versión pública local-first | Vigente |
