# Registro de decisiones (ADR)

Formato: contexto → decisión → consecuencias. Una decisión nueva se agrega al final. Una que cambia se marca como *Reemplazada por ADR-NNN* o *Actualizada por ADR-NNN*; no se borra.

Las ADR-001 a ADR-018 se tomaron entre el 2026-10-27 y el 2026-11-01, cuando JobBot era una herramienta de uso personal. La ADR-019 define la versión pública.

---

## ADR-001 — Python + Playwright

- **Fecha:** 2026-10-27. *Actualizada por ADR-019.*
- **Contexto:** los formularios de los ATS modernos son aplicaciones de una sola página, y el ecosistema reutilizable para buscar empleo está sobre todo en Python.
- **Decisión:** Python ≥ 3.11 con `uv`. HTTP con `httpx`. Playwright se planeó para el envío de postulaciones.
- **Consecuencias:** un solo lenguaje. Con la ADR-019 no hay envío: Playwright queda solo para generar los CV en PDF, como extra opcional (`resumes`).

## ADR-002 — SQLite como estado

- **Fecha:** 2026-10-27.
- **Contexto:** un usuario y un proceso a la vez.
- **Decisión:** SQLite (modo WAL) con `sqlite3` de la biblioteca estándar y migraciones por `PRAGMA user_version`. Sin ORM.
- **Consecuencias:** cero infraestructura. Cada usuario tiene su propia base en `JOBBOT_HOME/data/jobbot.db` y el respaldo es copiar un archivo.

## ADR-003 — Sin evasión anti-bot

- **Fecha:** 2026-10-27.
- **Contexto:** saltarse CAPTCHAs y fingerprinting viola los términos de uso de los sitios, arriesga las cuentas del usuario y es técnicamente frágil.
- **Decisión:** `User-Agent` honesto, sin stealth, sin resolvedores de CAPTCHA, sin fingerprint spoofing ni proxies rotativos. Si un sitio bloquea o muestra un challenge, esa fuente se detiene y se avisa al usuario.
- **Consecuencias:** menos cobertura en sitios que bloquean bots, compensada con fuentes que tienen API pública y con las alertas por correo.

## ADR-004 — Adapters deterministas por fuente

- **Fecha:** 2026-10-27. *Parte de envío reemplazada por ADR-019.*
- **Contexto:** pocos ATS concentran la mayoría de vacantes.
- **Decisión original:** un adapter por ATS, probado con fixtures. Para el envío en ATS desconocidos se planeó un modelo de lenguaje que navegara el sitio, siempre en modo de prueba.
- **Decisión vigente:** un adapter determinista por fuente de descubrimiento, probado con fixtures y sin red. No hay envío (ADR-019).
- **Consecuencias:** tests reproducibles y costo cero por consulta.

## ADR-005 — LinkedIn, Indeed y Wellfound sin automatización

- **Fecha:** 2026-10-27.
- **Contexto:** sus términos prohíben la automatización, y la cuenta de LinkedIn suele ser el activo profesional más valioso de quien busca empleo.
- **Decisión:** LinkedIn solo en modo asistido: sus alertas llegan al correo del usuario, JobBot las lee y el usuario postula. Indeed solo por sus alertas de correo (ADR-013). Wellfound se descarta (ADR-007).
- **Consecuencias:** JobBot nunca toca esas cuentas.

## ADR-006 — Envío autónomo con umbral de confianza

- **Fecha:** 2026-10-27. *Reemplazada por ADR-019.*
- **Contexto:** se buscaba reducir la intervención manual, pero un modelo de lenguaje puede inventar experiencia.
- **Decisión original:** enviar solo si todas las respuestas salían de `profile/` o eran texto validado contra `facts.yaml`, con confianza ≥ 0,85; si no, estado `NEEDS_INPUT` y una pregunta al usuario.
- **Consecuencias:** el envío se descartó en la ADR-019. Sigue vigente el principio: **nunca inventar datos del usuario**; si falta algo, se pregunta (grill-me) y la respuesta queda en `profile/`.

## ADR-007 — Prioridad de plataformas por valor × facilidad

- **Fecha:** 2026-10-27.
- **Contexto:** ordenar las fuentes por facilidad técnica ponía primero a Greenhouse, Lever y RemoteOK, que publican sobre todo roles de startups de EE. UU. con seniority o permiso de trabajo que un perfil junior en Latinoamérica no suele tener.
- **Decisión:** orden para el preset de Costa Rica: multinacionales con sitio de empleo propio (Workday y otros) → agencias de staffing → LinkedIn (asistido) → CompuTrabajo → BPO de soporte bilingüe → elempleo → bolsas remotas (Get on Board, Remotive, Jobicy, Himalayas) → Greenhouse / Lever / Ashby → Indeed (solo correo). Se descartan Wellfound y Encuentra24. Detalle en [`job-search.md`](job-search.md).
- **Consecuencias:** el descubrimiento empezó por Workday. Greenhouse y Lever se mantienen porque su API es simple y sirve para empresas que el usuario agregue.

## ADR-008 — Documentación mínima

- **Fecha:** 2026-10-27. *Actualizada por ADR-019.*
- **Contexto:** muchos documentos vacíos o solapados por adelantado hacen que nadie sepa cuál leer.
- **Decisión:** en la raíz, `README.md` (inglés) y `README.es.md` (qué es y cómo usarlo), `CONTRIBUTING.md` (reglas), `SECURITY.md` y `ROADMAP.md` (planes). En `docs/`, solo documentos con contenido real. Los valores que lee el bot viven en los YAML de configuración y nunca se copian en Markdown.
- **Consecuencias:** cada pregunta tiene un solo archivo que la responde.

## ADR-009 — Familias de roles

- **Fecha:** 2026-10-27.
- **Contexto:** una misma persona puede buscar en más de un área, por ejemplo soporte TI como búsqueda principal y datos como secundaria, con un CV distinto para cada una.
- **Decisión:** los filtros de título se agrupan en familias en `search.yaml: role_families`. Cada familia tiene `priority` (`primary` o `secondary`), su variante de CV (`cv:`) y un nombre opcional para mostrar (`label`). Cada vacante guarda su `role_family` (migración 2). Las exclusiones globales (seniority, ventas) aplican a todas.
- **Consecuencias:** `jobbot jobs --family <familia>` separa las búsquedas. Si un título encaja en dos familias, gana la principal.

## ADR-010 — CV generados desde el perfil

- **Fecha:** 2026-10-27. *Actualizada por ADR-019.*
- **Contexto:** cuando cada CV se edita a mano por separado, terminan contradiciéndose en niveles, certificaciones y fechas.
- **Decisión:** el contenido de cada variante vive en `profile/resumes/<variante>.yaml` (español e inglés) y `jobbot resumes` genera los PDF con una plantilla HTML y Chromium (Playwright). El contacto sale de `profile/private/contact.yaml`. Las afirmaciones prohibidas u obligatorias de cada usuario (por ejemplo, una certificación no aprobada que no puede aparecer como obtenida) se declaran en `profile/resumes/checks.yaml`, como listas `forbidden` y `required` de reglas `{pattern, reason}`. Si algún CV rompe una regla, el comando no genera ningún PDF.
- **Consecuencias:** un cambio de perfil se refleja en todos los CV con un comando. Los PDF quedan en `JOBBOT_HOME`, fuera del repositorio.

## ADR-011 — Sitios que bloquean bots y APIs con límite de uso

- **Fecha:** 2026-10.
- **Contexto:** CompuTrabajo responde 403 a cualquier cliente automatizado, incluso al pedir `robots.txt`. Remotive pide en sus términos un máximo de unas 4 consultas al día.
- **Decisión:** un sitio que bloquea al bot no se fuerza (ADR-003): CompuTrabajo entra por sus alertas de correo. Las fuentes con límite declaran `min_hours_between_runs` y el pipeline las omite si se consultaron hace menos, usando `last_seen_at` de la base. Para reaplicar filtros sin volver a consultar los sitios existe `jobbot rescreen`, que permite la transición `SKIPPED → DISCOVERED`.
- **Consecuencias:** se respetan los términos de cada fuente, y ajustar `search.yaml` no obliga a borrar la base.

## ADR-012 — Alertas por correo con Gmail de solo lectura

- **Fecha:** 2026-10.
- **Contexto:** LinkedIn prohíbe automatizar (ADR-005) y CompuTrabajo bloquea bots (ADR-011), pero ambos envían alertas de empleo al correo del usuario.
- **Decisión:** leer esas alertas desde Gmail con OAuth de app de escritorio y el permiso `gmail.readonly`, en vez de IMAP con contraseña. Cada usuario crea su propio cliente OAuth. La búsqueda se limita a los remitentes configurados y a los últimos `lookback_days`. Las vacantes entran como `email:<sitio>`. Si falta la configuración, la fuente se reporta como "sin configurar", no como error. `jobbot alerts-sample` guarda un correo real para ajustar los lectores.
- **Consecuencias:** cero contacto con LinkedIn y CompuTrabajo; el acceso se revoca desde la cuenta de Google. En estado de Prueba, Google vence la autorización más o menos cada 7 días. Las vacantes de correo no traen descripción, así que los filtros de descripción no aplican.

## ADR-013 — elempleo y Jibe directos; Indeed solo por correo

- **Fecha:** 2026-10-27.
- **Contexto:** el `robots.txt` de elempleo permite sus listados de búsqueda, y sus alertas por correo no siempre traen vacantes. Algunas empresas publican en Jibe, que tiene API pública y pide `crawl-delay: 5`. Indeed usa Cloudflare y enlaces de rastreo opacos.
- **Decisión:**
  - **elempleo:** se lee el listado público (`/cr/ofertas-empleo/<búsqueda>`) como máximo cada 12 h y con 5 s entre páginas. Además existe `email:elempleo`, que usa el mismo ID (`ats=elempleo`) para no duplicar.
  - **Jibe:** fuente `jibe`, filtrada por país en el código, con 5 s entre consultas.
  - **Indeed:** solo por alertas de correo. Si un enlace trae el ID de la vacante (`jk`), se usa la URL canónica; los enlaces de rastreo nunca se abren, porque implicaría visitar Indeed. Sin ID, la vacante se identifica por título, empresa y ubicación.
  - **`jobbot alerts-status`:** cuenta por sitio cuántas alertas llegaron, leyendo solo encabezados.
- **Consecuencias:** elempleo aporta vacantes aunque las alertas no lleguen. Sus listados no traen descripción, así que los filtros de descripción no aplican.

## ADR-014 — Corrida diaria programada

- **Fecha:** 2026-10. *Actualizada por ADR-019.*
- **Contexto:** buscar a mano cada día se olvida; el usuario quiere que JobBot busque solo y avise si hay algo nuevo.
- **Decisión:**
  - `jobbot daily` corre todas las fuentes, escribe `data/reports/<fecha>.html` y `latest.html`, y en Windows muestra una notificación solo si hay vacantes nuevas o una fuente necesita atención (por ejemplo, token de Gmail vencido). Al hacer clic se abre el informe.
  - En Windows lo programa `scripts/windows/install_schedule.ps1` (tarea "JobBot - busqueda diaria", que corre `scripts/windows/run_daily.ps1`), con *StartWhenAvailable*: si la computadora estaba apagada, corre al encenderla. En Linux y macOS, cron con `scripts/run_daily.sh` (ADR-019).
  - El registro queda en `data/logs/daily-<fecha>.log`.
  - Se descartaron Telegram y correo como canal de aviso porque piden credenciales nuevas.
- **Consecuencias:** cero costo y sin servicios externos. El aviso solo llega a la computadora. La tarea corre con la sesión del usuario iniciada.

## ADR-015 — CV recomendado por vacante y postulaciones manuales registradas

- **Fecha:** 2026-10.
- **Contexto:** el usuario postula a mano desde el informe y necesita ver, junto a cada vacante, qué CV subir. Además, las vacantes a las que ya postuló seguían apareciendo como pendientes.
- **Decisión:**
  - **CV recomendado:** la variante sale de la familia de roles (`cv:` en `search.yaml`) y el idioma, del anuncio. `matching/language.py` cuenta palabras frecuentes y tildes en español e inglés; el título pesa el triple y, si hay empate, gana el inglés, porque así publican las multinacionales. Se muestra en el informe, en el panel y en `jobbot jobs`.
  - **`jobbot applied <#…>`:** marca una vacante como `SUBMITTED` con motivo `applied_manually`, desde `DISCOVERED`, `SCORED`, `QUEUED` o `SKIPPED`. `--undo` revierte solo una marca manual.
  - **`jobbot report`:** regenera `latest.html` sin consultar fuentes. "Nuevas" son las de las últimas 24 h; las demás pendientes van en una sección plegable.
- **Consecuencias:** la detección de idioma es una heurística sin red y puede fallar en anuncios mixtos; si pasa, se ajustan las listas de palabras.

## ADR-016 — Panel local en el navegador

- **Fecha:** 2026-10.
- **Contexto:** pegar comandos en la consola para cada acción es incómodo para quien no programa.
- **Decisión:**
  - `jobbot panel` levanta un servidor HTTP de la biblioteca estándar en `127.0.0.1` (puerto en `settings.yaml: panel.port`) y abre la página en el navegador.
  - **La página** (`src/jobbot/panel/index.html`, sin frameworks ni CDN): pestañas Pendientes, Postuladas, Entrevistas, Cerradas y Descartadas (y Decisiones, ADR-019), con filtros por familia y búsqueda; botones "Ya postulé", "No me interesa", "Me llamaron", "Rechazo", "Volver a pendientes" y "Deshacer"; CV recomendado con enlace al PDF y botón para copiar su ruta; "Buscar ahora" con barra de avance, que usa lo mismo que la corrida diaria.
  - **Acceso directo (Windows):** `scripts/windows/install_shortcut.ps1` crea un acceso directo a `.venv\Scripts\jobbot-panel.exe` (`[project.gui-scripts]`), que corre sin ventana de consola y guarda su registro en `data/logs/panel.log`. Si el panel ya está abierto, solo abre la página. Se apaga solo tras 10 minutos sin uso.
  - **Seguridad:** solo escucha en `127.0.0.1` y exige su propio `Host` (contra DNS rebinding); las acciones solo se aceptan como POST JSON desde su propio `Origin` (contra CSRF) y nunca envía cabeceras CORS; los datos de las vacantes se insertan como texto, nunca como HTML; solo sirve PDF de CV con nombre válido.
  - **Decisiones del usuario:** "No me interesa" (`not_interested`) y "Volver a pendientes" (`reopened_manually`) quedan fuera de `rescreen`, para que cambiar los filtros no las revierta.
- **Alternativas descartadas:** Tkinter o Qt (aspecto anticuado o dependencias pesadas); interfaz de consola con Textual (seguía siendo una consola); hacer interactivo el informe HTML estático (no puede escribir en la base sin un servidor).
- **Consecuencias:** cero dependencias nuevas. El informe y los comandos siguen funcionando igual.

## ADR-017 — Trabajo remoto: bolsas remotas y filtro "100 % remoto"

- **Fecha:** 2026-10-28.
- **Contexto:** muchas personas buscan trabajo 100 % desde casa, idealmente con planilla local o en empresas abiertas a Latinoamérica. Get on Board y Remotive traían pocas vacantes elegibles: la mayoría de las de Latinoamérica exigían vivir en un país específico.
- **Decisión:**
  - **Fuentes nuevas** con API pública y términos que permiten este uso (detalle en [`platforms/job-boards.md`](platforms/job-boards.md)):
    - **Jobicy:** su filtro `geo` trae lo abierto al país, a Latinoamérica y a "Anywhere". Máximo una consulta por hora; se conserva su enlace.
    - **Himalayas:** búsqueda filtrada por país; JobBot además descarta lo que no admite el país ni su desfase horario. Se postula por su `applicationLink` sin cambios y no se republica.
    - Empresas en Workday con planilla local y vacantes remotas.
  - **Seniority:** las bolsas anotan la seniority al inicio de la descripción (`Seniority: Senior.`), para que `description.exclude` la filtre con su motivo. La ubicación queda como `Remote - <región>` para que la evalúen las reglas de `location`.
  - **`remote` significa 100 % remoto.** Los híbridos quedan en `False`. El panel etiqueta cada vacante como "100 % remoto", "Nacional" (presencial o híbrido en el país del usuario, según `location.local`) u "Otro país", y filtra por las dos primeras.
  - **Idiomas:** `title.exclude` puede descartar títulos que piden un idioma que el usuario no habla.
- **Revisadas y no automatizadas:** Concentrix (Phenom sin endpoint público), TELUS Digital (responde 403 al bot, ADR-003) y Movate (títulos genéricos; el puesto real solo aparece en la descripción).
- **Consecuencias:** entran más vacantes remotas, con más ruido de soporte al cliente no técnico, que el usuario descarta con "No me interesa". Muchas son por contrato; la diferencia con planilla se explica en [`job-search.md`](job-search.md).

## ADR-018 — Postulaciones confirmadas por correo

- **Fecha:** 2026-11-01.
- **Contexto:** el usuario postula en los sitios y luego marca "Ya postulé" en el panel. Si lo olvida, la vacante sigue en pendientes y puede postular dos veces. Los sitios ya envían un correo al confirmar cada postulación.
- **Decisión:**
  - **Fuente nueva:** `email:postulaciones` (`discovery/applications.py`). Lee esos correos con el mismo Gmail de solo lectura (ADR-012). Las consultas están en `targets.yaml: email_alerts.confirmations` y la fuente corre después de las alertas.
  - **Qué identifica cada sitio:**
    - **LinkedIn:** la vacante exacta, por su ID. Las "similares" del mismo correo no se tocan.
    - **Indeed:** título, empresa y lugar, sin ID. Se marcan las pendientes con la misma empresa y título, de cualquier fuente.
    - **CompuTrabajo:** solo el título. Se marca únicamente si hay una sola pendiente de CompuTrabajo con ese título; las vacantes dentro del correo son recomendaciones.
    - **elempleo:** su confirmación no dice a qué vacante se postuló; no se usa.
  - **Marca:** `SUBMITTED` con motivo `applied_by_email`. Si JobBot nunca había listado la vacante, la guarda ya postulada, para que el aviso "Ya postulaste" funcione con otras fuentes.
  - **Deshacer:** desde el panel o con `jobbot applied --undo`. La vacante vuelve a pendientes con `reopened_manually` y JobBot no la vuelve a marcar.
- **Consecuencias:** releer los mismos correos no cambia nada. El valor está en las postulaciones futuras.

## ADR-019 — Versión pública local-first

- **Fecha:** 2026-11-03.
- **Contexto:** JobBot nació como una herramienta personal, con los datos de su usuario dentro del repositorio y la configuración pensada para un solo país. Para publicarlo como código abierto hay que separar código y datos, permitir otros países y dejar claro que cada persona lo corre en su propia computadora.
- **Decisión:**
  - **Carpeta de datos `JOBBOT_HOME`:** por defecto la carpeta visible `JobBot` en el directorio del usuario. Contiene `config/`, `profile/`, `data/` y `.env`. Nada de eso vive en el repositorio.
  - **Plantillas y presets** dentro del paquete (`src/jobbot/templates/`): la configuración de cada preset, un perfil de ejemplo ficticio y la plantilla de `.env`. `jobbot init --preset <nombre>` los copia sin sobrescribir. Presets iniciales: `costa-rica-it` (por defecto) y `remote-latam`.
  - **Bloque `region`** en `settings.yaml` (`country`, `country_code`, `country_slug`, `utc_offset`, `timezone`), que las fuentes usan salvo que su entrada diga otra cosa. Sin país, una fuente se reporta como "sin configurar" en vez de adivinar. Las reglas de ubicación usan nombres genéricos: `location.local` y `location.local_exclude`.
  - **`disabled_sources`** en `settings.yaml`: fuentes que las búsquedas saltan sin borrarlas de `targets.yaml`.
  - **Extras opcionales:** `gmail` (alertas y confirmaciones; además, `email_alerts.enabled` viene en `false`) y `resumes` (PDF con Playwright + Chromium). Lo específico de Windows va en `scripts/windows/`, sin extra; en Linux y macOS, cron con `scripts/run_daily.sh`.
  - **grill-me:** `jobbot grill setup-profile` entrevista al usuario por rondas (preguntas numeradas, opciones cortas, recomendada solo en preferencias, confirmación antes de escribir). Los cambios se escriben con `ruamel.yaml` para conservar los comentarios de los archivos del usuario. Después de cada `jobbot daily`, tres detectores deterministas proponen hasta 3 preguntas nuevas por día, que se responden en la pestaña Decisiones o con `jobbot grill pendientes`. La versión 1 no usa ningún modelo de lenguaje.
  - **Nunca postular:** JobBot solo descubre y asiste. Reemplaza las partes de envío de las ADR-004 y ADR-006.
  - **Revisiones de CV por usuario:** las frases prohibidas y obligatorias pasan a `profile/resumes/checks.yaml`, en vez de estar en los tests.
  - **Historial público nuevo:** el repositorio público empieza con un historial limpio, sin commits del desarrollo personal.
  - **Privacidad verificable:** CI corre tests y lint en Windows, Linux y macOS, más `scripts/privacy_scan.py` sobre los archivos versionados. Cada colaborador puede sumar su propia lista de términos personales (`--denylist`), guardada fuera del repositorio.
- **Consecuencias:**
  - Cualquier persona puede usarlo eligiendo un preset, y agregar su país con un preset nuevo.
  - Actualizar (`git pull` + `uv sync`) no toca los datos del usuario, y el respaldo es copiar una carpeta.
  - Las opciones nuevas de las plantillas no llegan solas a archivos que el usuario ya tiene: `init` solo agrega los que faltan.

## ADR-020 — Vacantes recientes primero

- **Fecha:** 2026-11-09.
- **Contexto:** postular en las primeras horas de una vacante aumenta las chances, pero JobBot no mostraba la fecha de publicación. «Nueva» significaba «JobBot la vio hace menos de 24 h», así que una vacante de hace meses podía salir como nueva. Además, los correos de LinkedIn mezclan dos cosas: las alertas guardadas, que traen solo vacantes publicadas desde la alerta anterior (su enlace «ver todos» lleva `f_TPR=a<hora de la alerta anterior>`), y las recomendaciones («Nuevos empleos similares a…», las sugerencias bajo una confirmación de postulación, o una alerta sin resultados que manda similares), que pueden ser viejas.
- **Decisión:**
  - **Fecha de publicación en todo:** el panel y el informe muestran «publicada hace X». Si el sitio solo da una edad relativa, la fecha lleva «~»: Workday («Posted 3 Days Ago»), y LinkedIn, donde se usa la fecha del correo de la alerta guardada. Sin fecha: «fecha de publicación desconocida». Columnas nuevas `posted_approx` y `recommended` (migración 4).
  - **`fresh_hours`** en `search.yaml` (24 por defecto) define qué cuenta como reciente:
    - «Nueva» pasa a significar publicada en ese plazo; si la fecha es desconocida, vista por primera vez en las últimas 24 h.
    - el panel suma el filtro «Últimas 24 h», y las pendientes se ordenan por fecha de publicación;
    - el informe abre con «Publicadas en las últimas 24 h»;
    - el aviso de Windows dice cuántas hay.
  - **Recomendaciones de LinkedIn:** se siguen leyendo, con la marca «Recomendada por LinkedIn, puede ser vieja», y van al final de las pendientes. Si una alerta guardada lista la misma vacante, pierde la marca y toma la fecha de la alerta.
  - **Etiqueta de seniority de las bolsas:** pasa de `description.exclude` a `description.seniority`. Una vacante publicada menos de `fresh_hours` antes de verla pasa igual, con motivo `fresh_seniority` y la marca «La bolsa la marca senior». Los títulos con Senior, Lead o L3 siguen fuera. `rescreen` mide la frescura contra la primera vez que se vio la vacante.
  - **Búsquedas de LinkedIn de las últimas 24 h:** `targets.yaml: linkedin_searches` (palabras clave y `geo_id`) arma enlaces a la búsqueda de LinkedIn con `f_TPR=r<segundos>` y `sortBy=DD`, sin filtro de nivel. Aparecen como botones en el panel y como enlaces en el informe. JobBot nunca los abre: los abre el candidato en su navegador (ADR-005).
- **Consecuencias:**
  - Con fecha confiable quedan las bolsas remotas, Amazon, elempleo, SuccessFactors y Recruitee; con fecha aproximada, Workday y las alertas de LinkedIn. Indeed y CompuTrabajo por correo siguen sin fecha.
  - Una instalación anterior conserva su `search.yaml` y su `targets.yaml`: para tener el filtro aflojado y los botones, hay que copiar `fresh_hours`, `description.seniority` y `linkedin_searches` desde el preset.

## ADR-021 — Empresas remotas: Ashby, Deel y `remote_scope`

- **Fecha:** 2026-11-10.
- **Contexto:** varias empresas 100 % remotas contratan en Latinoamérica, pero no publican en las bolsas que JobBot ya lee. Revisión del 2026-11-10 de GitLab, Automattic, Deel, Remote.com, Hubstaff, Buffer, Civo y Loka:
  - **Greenhouse:** GitLab (`gitlab`), Automattic (`automatticcareers`) y Loka (`lokainc`). Según su handbook, GitLab contrata en Costa Rica por PEO y solo para ciertos puestos. Ya publicó soporte AMER con «Remote, Costa Rica».
  - **Ashby:** Hubstaff y Buffer.
  - **Teamtailor (RSS público):** Civo. Su soporte es presencial y vende en India, así que no se agrega.
  - **Página propia:** Deel (`deel.com/careers`, con el país de cada vacante dentro de la página) y Remote.com (`remote.com/openings`, solo títulos). Sus tableros en Ashby y Greenhouse están vacíos.
  - Automattic publica «Remote» sin país aunque contrata en cualquiera; para los filtros eso es `remote_region_unknown`.
- **Decisión:**
  - **Fuente nueva `ashby`** (`discovery/ashby.py`): API pública `posting-api/job-board/{board}`, sin clave, una consulta por empresa.
  - **`remote_scope`** por empresa en Greenhouse y Ashby: qué significa un «Remote» sin lugar (p. ej. `Worldwide`). Solo cambia esa ubicación exacta; las que nombran un lugar quedan igual.
  - «IT Engineer» y «Happiness Engineer» (soporte de Automattic) entran a la familia de soporte TI. Senior, Lead y nivel 3 siguen fuera.
  - **Fuente nueva `deel`** (`discovery/deel.py`): lee las vacantes que trae su propia página de empleos, con los países de cada una. `robots.txt` lo permite; corre cada 12 h.
  - Remote.com no se agrega: su lista no dice el país, así que no se puede saber cuáles son para Costa Rica.
  - Civo no se agrega.
- **Consecuencias:** las tres APIs son gratuitas y públicas. Con empresas remotas grandes (GitLab tiene más de 250 vacantes), casi todo se descarta por título o ubicación. El valor es enterarse el día que abren algo para el perfil y el país.

## ADR-022 — Portales iCIMS y empresas donde sirve cualquier puesto

- **Fecha:** 2026-11-11.
- **Contexto:** varias empresas con oficinas en Costa Rica publican solo en su portal iCIMS (`jobs-<empresa>.icims.com`), que no tiene API pública, pero sí una búsqueda pública que el `robots.txt` permite. Además, a veces lo que interesa es entrar a una empresa concreta, en el puesto que sea, y los filtros por familia de roles descartaban todo lo que no fuera de TI o datos.
- **Decisión:**
  - **Fuente nueva `icims`** (`discovery/icims.py`): lee la búsqueda del portal con `in_iframe=1`, página por página, filtrada por lo que el usuario copia de la URL (`search`). La ficha de cada vacante, con su JSON-LD (`datePosted`, `description`), se pide solo para las que pasan título y ubicación.
  - **`any_role_companies`** en `search.yaml`: las vacantes de esas empresas pasan sin familia de roles. `title.exclude` (seniority), la ubicación y la descripción siguen aplicando. Quedan sin familia: el informe las agrupa en "Otras" y reciben el CV de la primera familia.
  - Las empresas concretas viven en la configuración de cada usuario. Los presets traen las dos claves vacías.
- **Consecuencias:** cuando cambie el formato del portal, la fuente deja de encontrar tarjetas sin dar error, así que conviene revisar la línea de la fuente en la salida de la búsqueda. El sitemap del portal (`/sitemap.xml`) es una alternativa si hace falta.

## ADR-023 — Vacantes en español de la región y límite de un mes

- **Fecha:** 2026-11-11.
- **Contexto:** el candidato quiere vacantes en español de otros países de Latinoamérica que pueda hacer desde Costa Rica, y que nada de lo que puede postular tenga más de un mes. En 30 días JobBot vio 729 vacantes en español. Las 65 de sus familias descartadas por ubicación eran casi todas presenciales o "remoto, debes vivir en el país" en Chile, Colombia o Perú, así que estaba bien descartarlas. Pero había huecos:
  - Los filtros no reconocían las regiones escritas en español.
  - Una vacante en español que decía solo "Remoto" se descartaba.
  - Las búsquedas de LinkedIn eran solo del país.
  - Además, Descartadas mezclaba vacantes de meses atrás y no había forma de sacar de la lista las ya revisadas.
- **Decisión:**
  - **Regiones en español** en `location.remote_ok` de los presets: Latinoamérica, América Latina, cualquier país, todo el mundo.
  - **"Remoto" sin lugar:** si el anuncio está en español, pasa con la nota `remote_no_country` ("Remoto sin país: confirma que acepten <país>"). En inglés sigue siendo `remote_region_unknown`.
  - **`max_age_days`** en `search.yaml` (30 en los presets; 0 = sin límite):
    - lo publicado antes se descarta al llegar (`too_old: N días`);
    - en cada corrida, `expire_old` manda a Descartadas las pendientes que pasan el límite, contando desde que JobBot la vio si no tiene fecha;
    - las reabiertas a mano no se tocan;
    - `rescreen` aplica la misma regla;
    - el "Posted 30+ Days Ago" de Workday cuenta como 31 días.
  - **`linkedin_searches`** pasa a ser una lista de grupos, cada uno con `label` y opcionalmente `remote_only` (filtro "En remoto"). El preset de Costa Rica suma "Latinoamérica remoto" (`location: Latinoamérica`, palabras en español). Un bloque único sigue funcionando como un grupo.
  - **Panel:**
    - "Ordenar por" (fecha de publicación, cuándo la vio JobBot o empresa) en todas las pestañas;
    - filtro "En español", con el idioma detectado del anuncio;
    - en Descartadas, solo lo del último `max_age_days` y el botón "Quitar de la lista". Columna `hidden`, migración 5; `rescreen` no toca las ocultas.
  - **Torre.ai no se lee:** sus términos prohíben recorrer y extraer el sitio, y su `robots.txt` bloquea la búsqueda. Las vías legítimas son su API para profesionales, con clave del usuario, o sus correos de alertas.
  - **Actualización 2026-11-12:** se eligió el correo. El feed `email:torre` lee los correos de vacantes de Torre (`emma@torre.ai` y las alertas de `torre@torre.ai`). La opción `remote_scope` del feed, la misma de Greenhouse y Ashby, hace que su "Remote" sin país cuente como elegible, porque Torre ya filtró por el país del candidato.
- **Consecuencias:** la nota de "Remoto sin país" puede dejar pasar vacantes que en realidad son de otro país; por eso se marca. Las vacantes de correo sin fecha duran como máximo `max_age_days` desde que llegaron.

## ADR-024 — Primer empleo: filtro Entrada, nota de matrícula y búsquedas por nivel

- **Fecha:** 2026-11-14.
- **Contexto:** el candidato quiere un apartado de pasantías y de primer empleo, y ver también puestos de software y de IA y automatización aunque todavía le queden grandes. Ya es egresado, y la mayoría de las pasantías piden estar matriculado. En la base había 72 títulos de pasantía o trainee, casi todos de otras áreas.
- **Decisión:**
  - **Filtro "Entrada"** en el panel: marca pasantías, trainee, aprendiz, programas de graduados, new grad, early career y junior (`matching.rules.entry_level`, sobre el título). No es una familia: atraviesa todas.
  - **Nota `enrollment_required`:** si la descripción pide estar matriculado ("currently enrolled", "estudiante activo", "estar cursando"…), la vacante pasa con la marca «Pide estar matriculado: revisa si aceptan egresados». Cuando el anuncio acepta a la vez estudiantes y recién graduados no se marca. Las vacantes sin descripción, como las que llegan por correo, no reciben la nota.
  - **`linkedin_searches`:** cada grupo acepta `experience`, el filtro de nivel de LinkedIn (`f_E`): `internship`, `entry` o `associate`. También acepta `hours`, su propio rango hacia atrás, porque una semana sirve mejor para las pasantías. El panel y el informe dicen el rango de cada grupo («últimos 7 días»).
  - **Familias nuevas sin código nuevo:** "Software / automatización" (solo con marca de entrada) e "IA y automatización · aspiracional" son configuración en `search.yaml`. La palabra "aspiracional" en la etiqueta basta para distinguirlas en el panel y el informe. La automatización industrial (PLC, equipos) queda fuera con su `exclude`.
- **Consecuencias:** la nota de matrícula depende de la redacción del anuncio, así que puede faltar o sobrar: es un aviso, no un filtro. El filtro "Entrada" no incluye los niveles 1 (L1, "Analyst I"), que ya son el foco de las familias de soporte.
