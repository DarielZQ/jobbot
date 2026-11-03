# Greenhouse y Lever

**Estado:** descubrimiento disponible (`discovery/greenhouse.py`, `discovery/lever.py`) y probado con fixtures. Los presets no traen empresas en estas plataformas: se agregan según la búsqueda de cada usuario. La postulación la hace el usuario en el sitio de la empresa.

## Greenhouse

- **Listado:** `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`. Público, sin autenticación.
- `token` = última parte de `boards.greenhouse.io/{token}` o `job-boards.greenhouse.io/{token}`.
- `content` viene con HTML escapado dos veces; `normalize_text` lo resuelve.
- **Configuración:** `greenhouse: [{ company, token }]` en `targets.yaml`.

## Lever

- **Listado:** `GET https://api.lever.co/v0/postings/{slug}?mode=json`. Público, sin autenticación.
- `slug` = última parte de `jobs.lever.co/{slug}`.
- `workplaceType`: `remote | hybrid | onsite | unspecified`.
- `createdAt` viene en milisegundos desde epoch.
- **Configuración:** `lever: [{ company, slug }]` en `targets.yaml`.
