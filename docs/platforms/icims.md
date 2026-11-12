# iCIMS

**Última verificación:** 2026-11-11 · **Estado:** descubrimiento disponible (`discovery/icims.py`). La postulación la hace el usuario en el portal de la empresa.

## Descubrimiento (sin login)

iCIMS no tiene una API pública de vacantes. Cada empresa tiene un portal `jobs-<empresa>.icims.com` cuya búsqueda es pública. El `robots.txt` típico solo bloquea login, referidos y la cuenta del candidato, pero hay que revisarlo en cada empresa antes de agregarla.

- **Listado:** `GET https://{host}/jobs/search?ss=1&{search}&in_iframe=1&pr={página}`. El portal muestra los resultados dentro de un iframe, y `in_iframe=1` devuelve esa página interna. Cada vacante es un `li.iCIMS_JobCardItem` con lugar (`Job Locations`), título (`h3`), enlace `/jobs/{id}/{slug}/job` y un resumen.
- **Paginación:** `pr=0, 1, 2…`. Si se pide una página después de la última, el portal repite la última, así que la fuente para cuando una página no trae nada nuevo (máximo 10).
- **Detalle:** `GET {enlace}?in_iframe=1` trae un `JobPosting` de schema.org en JSON-LD con `datePosted` y `description`. Solo se pide para las vacantes que pasan los filtros de título y ubicación (`enrich`).
- **Lugar:** `CR-H-Costa Rica | CO-Bogotá` (código de país, código de región y lugar, separados por `|` si hay varios). Los filtros de ubicación lo leen tal cual.

## Configuración

En `targets.yaml`:

```yaml
icims:
  - { company: "Acme", host: jobs-acme.icims.com, search: "searchLocation=<id>-<id>-<País>" }
```

Para sacar `search`, filtra el portal por tu país y copia lo que sigue a `/jobs/search?ss=1&` en la URL. Sin `search`, la fuente lee todas las vacantes de la empresa.

## Cualquier puesto en una empresa

Si te interesa cualquier puesto de esa empresa, agrega su nombre (el mismo `company`) a `any_role_companies` en `search.yaml`. Sus vacantes pasan aunque el título no sea de ninguna familia; Senior, Lead y Manager siguen fuera (ADR-022).
