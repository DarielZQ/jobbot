# Greenhouse, Lever y Ashby

**Estado:** descubrimiento disponible (`discovery/greenhouse.py`, `discovery/lever.py`, `discovery/ashby.py`) y probado con fixtures. Los presets no traen empresas en estas plataformas: se agregan según la búsqueda de cada usuario. La postulación la hace el usuario en el sitio de la empresa. **Última verificación:** 2026-11-10.

Las tres son APIs públicas y gratuitas: listar vacantes no pide clave ni cuenta. JobBot hace una consulta por empresa en cada búsqueda y los filtros de `search.yaml` dejan solo lo que es para tu país o remoto elegible, igual que el filtro de ubicación del sitio.

## Greenhouse

- **Listado:** `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`. Público, sin autenticación.
- `token` = última parte de `boards.greenhouse.io/{token}` o `job-boards.greenhouse.io/{token}`. No siempre es el nombre de la empresa: Automattic es `automatticcareers` y Loka, `lokainc`. Un token puede existir y estar vacío (`remotecom` devuelve 0 vacantes: Remote.com publica en su propia página).
- `content` viene con HTML escapado dos veces; `normalize_text` lo resuelve.
- **Configuración:** `greenhouse: [{ company, token, remote_scope }]` en `targets.yaml`.

## Lever

- **Listado:** `GET https://api.lever.co/v0/postings/{slug}?mode=json`. Público, sin autenticación.
- `slug` = última parte de `jobs.lever.co/{slug}`.
- `workplaceType`: `remote | hybrid | onsite | unspecified`.
- `createdAt` viene en milisegundos desde epoch.
- **Configuración:** `lever: [{ company, slug }]` en `targets.yaml`.

## Ashby

- **Listado:** `GET https://api.ashbyhq.com/posting-api/job-board/{board}`. Público, sin autenticación; trae todas las vacantes y su descripción en una sola respuesta.
- `board` = última parte de `jobs.ashbyhq.com/{board}`.
- La ubicación sale de `location` más `secondaryLocations[].location`. `isRemote` o `workplaceType: Remote` marcan el remoto; `publishedAt` es la fecha de publicación.
- Las vacantes con `isListed: false` se saltan.
- Un tablero puede existir y estar vacío: Deel (`Deel`) usa Ashby por dentro, pero lista sus vacantes en su propia página.
- **Configuración:** `ashby: [{ company, board, remote_scope }]` en `targets.yaml`.

## `remote_scope`: un «Remote» sin país

Algunas empresas publican la ubicación como «Remote», sin decir desde dónde. Para JobBot eso es `remote_region_unknown` y la vacante se descarta. Si sabes que en esa empresa «Remote» significa cualquier país (Automattic), pon `remote_scope: "Worldwide"`: la ubicación pasa a «Remote - Worldwide» y la aceptan los `remote_ok`. Una ubicación que sí nombra un lugar no cambia. Vale para Greenhouse y Ashby (ADR-021).
