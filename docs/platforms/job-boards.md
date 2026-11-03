# Bolsas y sitios con API pública

Amazon, Get on Board, Remotive, Jobicy, Himalayas, Recruitee, elempleo y Jibe.

**Última verificación:** 2026-10-28 · **Estado:** descubrimiento disponible. La postulación la hace el usuario en el sitio de cada vacante.

Ninguna de estas fuentes pide login. Los límites de cada una se respetan con `min_hours_between_runs` (en `targets.yaml`) y con el intervalo por host de `settings.yaml`.

Las fuentes que buscan por país toman el valor de `settings.yaml: region` salvo que su entrada en `targets.yaml` diga otro. Si no hay país, se reportan como "sin configurar" en vez de adivinar.

## amazon.jobs (`discovery/amazon.py`)

- **Listado:** `GET https://www.amazon.jobs/en/search.json?normalized_country_code[]=<país>&result_limit=100&offset=N`. Es el JSON que usa el propio sitio. Su `robots.txt` solo bloquea rutas `/internal`.
- **País:** código ISO de 3 letras; por defecto, `region.country_code`.
- **Campos usados:** `id_icims` (ID), `title`, `normalized_location`, `job_path`, `description`, `basic_qualifications` y `posted_date` (`"October 20, 2026"`).
- **No** se usan `preferred_qualifications`: son opcionales y su "3+ years" descartaría vacantes de entrada.

## Get on Board (`discovery/getonboard.py`)

- **Búsqueda:** `GET https://www.getonbrd.com/api/v0/search/jobs?query=...&per_page=50&page=N&expand=["company"]`. API pública documentada.
- **`remote_modality`:**
  - `fully_remote`: se trata como `Remote - LATAM`.
  - `remote_local`: hay que vivir en el país de la empresa.
  - `hybrid` o `no_remote`: presencial en `countries`.
- **Seniority** (`/api/v0/seniorities`): 1 Sin experiencia, 2 Junior, 3 Semi Senior, 4 Senior, 5 Expert. Se antepone a la descripción (`"Seniority: Junior."`) y `search.yaml` descarta Senior y Expert con motivo visible. Semi Senior pasa.
- La misma vacante aparece en varias búsquedas; la fuente deduplica por `id`.

## Remotive (`discovery/remotive.py`)

- **Listado:** `GET https://remotive.com/api/remote-jobs?category=<categoría>` (por ejemplo `customer-support` y `data`).
- **Términos de uso:**
  - Máximo unas 4 consultas al día: la fuente espera `min_hours_between_runs: 6`.
  - No republicar las vacantes y enlazar a la URL de Remotive (JobBot guarda esa URL).
  - Las vacantes llegan con 24 h de retraso.
- **Elegibilidad:** `candidate_required_location`. "Worldwide", "LATAM" o "Americas" pasan; "USA" se descarta.
- La API pública devuelve pocas vacantes por categoría.

## Jobicy (`discovery/jobicy.py`)

- **Listado:** `GET https://jobicy.com/api/jobs?count=200&geo=<país>`. Si hay más páginas, se sigue `nextCursor`. Sin clave. Documentación: `github.com/Jobicy/remote-jobs-api`.
- **`geo`:** por defecto, `region.country_slug` (p. ej. `costa-rica`). Incluye las vacantes "Anywhere" y de Latinoamérica. Los valores vigentes salen de `?get=locations`.
- **Contenido:** el feed cubre los últimos 7 días.
- **Uso justo** (sección *Fair Use* de su documentación):
  - Conservar la URL de Jobicy y citarlo como fuente.
  - No iniciar una consulta automática nueva más de una vez por hora: `min_hours_between_runs: 1`.
  - No republicar las vacantes como propias.
- **Campos usados:** `id`, `jobTitle`, `companyName`, `jobGeo` (la ubicación queda `Remote - <jobGeo>`), `jobLevel`, `jobDescription` (HTML), `pubDate` (ISO) y `url`.
- **Seniority:** si `jobLevel` solo dice Senior, Director o similar, se antepone `Seniority: Senior.` y la regla de descripción la descarta. "Any", "Entry-Level", "Junior" y "Midweight" pasan.
- Algunas vacantes son solo para un país distinto del tuyo; se descartan como `remote_region_unknown`.

## Himalayas (`discovery/himalayas.py`)

- **Búsqueda:** `GET https://himalayas.app/jobs/api/search?q=...&country=<país>&page=N`. Sin clave; las consultas sin clave comparten un cupo público, por eso `min_hours_between_runs: 6`. Las búsquedas se configuran en `targets.yaml: himalayas.queries`.
- **Paginación:** una página puede traer menos de 20 resultados antes del final. Se pide la siguiente hasta recibir una vacía o llegar a `max_pages`.
- **Elegibilidad:** según su documentación, una vacante está abierta a un país si `locationRestrictions` está vacío o lo incluye, y si `timezoneRestrictions` incluye su desfase estándar. JobBot lo verifica con `region.country` y `region.utc_offset`.
- **Términos de la API:**
  - Postular por `applicationLink` sin cambios: JobBot lo guarda como URL.
  - Mostrar Himalayas como fuente: el panel muestra la fuente `himalayas`.
  - Mostrar las vacantes solo en apps propias y no pasarlas a otras bolsas.
- **Seniority:** `seniority` es una lista. Si no incluye "Entry-level" ni "Mid-level", se antepone `Seniority: Senior.`.
- `pubDate` viene en segundos Unix.

## Recruitee (`discovery/recruitee.py`)

- **Listado:** `GET https://<subdominio>.recruitee.com/api/offers/`. Público.
- **Configuración:** `recruitee: [{ company, subdomain }]` en `targets.yaml`.

## elempleo (`discovery/elempleo.py`)

- **Listado:** `GET https://www.elempleo.com/cr/ofertas-empleo/<búsqueda>` (HTML). Su `robots.txt` no lo prohíbe. JobBot lo consulta como máximo cada 12 h, con 5 s entre páginas.
- Cada resultado es un bloque `result-item` con `js-offer-title` (título y enlace `/cr/ofertas-trabajo/<slug>/<id>`), `js-offer-company`, `js-offer-city` y `js-offer-date` ("Publicado 23 Oct 2026").
- El listado no trae descripción, así que los filtros de descripción no aplican.
- Las búsquedas se configuran en `targets.yaml: elempleo.searches`.
- `email:elempleo` comparte el ID (`ats=elempleo`): una vacante que llega por correo y por listado se guarda una sola vez.

## Jibe (`discovery/jibe.py`)

- **Listado:** `GET https://<host>.jibeapply.com/api/jobs?page=N&limit=100`. Los sitios revisados tienen `robots.txt` con `Allow: /` y `crawl-delay: 5`, configurado en `settings.yaml: http.host_min_interval_s`.
- El filtro `location` de la API puede no funcionar, así que la fuente trae todo y filtra por `country` en el código (por defecto, `region.country`).
- **URL pública** de cada vacante: `https://<host>.jibeapply.com/jobs/<slug>`. La postulación puede terminar en otro ATS (por ejemplo iCIMS).
- **Configuración:** `jibe: [{ company, host }]` en `targets.yaml`. Los presets no traen sitios Jibe configurados.

## Revisados y no automatizados

| Sitio | Motivo | Alternativa |
| :--- | :--- | :--- |
| CompuTrabajo | Responde 403 a clientes automatizados, incluso en `robots.txt` (ADR-011) | Alertas por correo ([`email-alerts.md`](email-alerts.md)) |
| Agencias que reciben CV solo por WhatsApp | Sin sitio de empleo consultable | Canal manual |
| Concentrix, TEKsystems (Phenom) | Sin endpoint público verificado | Revisar a mano o con alertas |
| TELUS Digital | Responde 403 al bot (ADR-003) | Revisar a mano |
| Teleperformance | Sitio sin verificar | Revisar a mano |
