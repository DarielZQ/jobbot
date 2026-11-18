# SAP SuccessFactors (Career Site Builder)

**Última verificación:** 2026-11-17 · **Estado:** descubrimiento disponible (`discovery/successfactors.py`), solo en sitios que muestran la lista sin JavaScript. La postulación la hace el usuario en el sitio de la empresa.

## Cómo reconocerlo

URLs del tipo `/go/<Nombre>/<id>/` para listados y `/job/<Ciudad>-<Título>/<id>/` para vacantes, normalmente en un dominio propio de la empresa (por ejemplo `jobs.foundever.com`).

## Qué permite el `robots.txt`

Es el mismo en todas las empresas revisadas (Foundever, Wipro, Boston Scientific):

- **Prohíbe `/services/`.** Ahí están el feed RSS (`/services/rss/job/`) y la API JSON (`/services/recruiting/v1/jobs`). JobBot no los usa (ADR-028).
- **Permite `/search/` y `/job/`**, que son la página de búsqueda y el detalle de cada vacante.

## Descubrimiento (sin login)

- **Lista:** `GET {base_url}/search/?q=&locationsearch=<país>&locale=en_US`. Cada vacante es una fila `<tr class="data-row">` con:
  - el enlace `jobTitle-link`, que trae el título y la ruta `/job/.../<id>/`;
  - `jobLocation`, con la ubicación ("Heredia, Costa Rica, CR");
  - `jobDate` ("Nov 4, 2026"), que no todos los sitios muestran.
- **Paginación:** 25 por página con `&startrow=<n>`. El total sale de `paginationLabel` ("Results 1 – 25 of 323"). Si se leyeron todas, la fuente marca el listado como completo, y una vacante que deja de aparecer se marca "Ya no aparece en el sitio" (ADR-026).
- **Sin resultados:** la página trae `id="noresults"`. Se toma como un listado completo y vacío.
- **Detalle (`enrich`):** solo para las vacantes que pasan los filtros de título y ubicación. Es un `GET` a la URL de la vacante. La descripción es el HTML dentro de `<span class="jobdescription">` y la fecha sale de `<meta itemprop="datePosted">`.

## Sitios que no se pueden leer

El diseño nuevo del sitio («unify», por ejemplo `careers.wipro.com`) no trae la lista en el HTML: la carga con JavaScript desde `/services/recruiting/v1/jobs`. En esos sitios la fuente falla con el mensaje «la página de búsqueda no trae la lista de vacantes…», y la empresa se sigue con alertas de LinkedIn.

El `sitemap.xml` de Wipro lista todas sus vacantes (unas 7000), con el código del país en la ruta (`-CRI`). No se usa: habría que descargar más de 1 MB al día para encontrar una o dos de Costa Rica, y el detalle redirige a otra ruta.

## Configuración

En `targets.yaml`:

```yaml
successfactors:
  - { company: "Acme Corp", base_url: "https://jobs.acme.example" }
```

- `keywords` es opcional: es el lugar que se escribe en la búsqueda («costa rica»). Por defecto se usa `region.country` en minúsculas. Sin país, la fuente se reporta como "sin configurar".
- `locale` es opcional (por defecto `en_US`).
