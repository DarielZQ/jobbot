# Workday

**Última verificación:** 2026-10-27 · **Estado:** descubrimiento disponible (`discovery/workday.py`). La postulación la hace el usuario en el sitio de la empresa.

## Descubrimiento (sin login)

El sitio de empleo de cada empresa usa un endpoint JSON propio, sin autenticación:

- **Listado:** `POST https://{host}/wday/cxs/{tenant}/{site}/jobs` con
  `{"appliedFacets": {...}, "limit": 20, "offset": N, "searchText": ""}`. El máximo por página es 20.
- **Detalle:** `GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}` → `jobPostingInfo.jobDescription` (HTML). Solo se pide para las vacantes que pasan los filtros de título y ubicación (`enrich`).
- **URL pública:** `https://{host}/{site}{externalPath}`.

## Configuración

En `targets.yaml`:

```yaml
workday:
  - { company: "Acme Corp", host: acme.wd5.myworkdayjobs.com, tenant: acme, site: External }
```

- `country` es opcional: por defecto se usa `region.country` de `settings.yaml`. Sin país, la fuente se reporta como "sin configurar".
- Para encontrar `host`, `tenant` y `site`, copia la URL de la página de empleos de la empresa y pruébala:

  ```bash
  uv run python scripts/probe_workday.py https://acme.wd5.myworkdayjobs.com/External
  ```

  Si responde, imprime la línea lista para pegar.

## Particularidades

- **El filtro de país cambia de nombre según la empresa:** `locationCountry` (Kyndryl, Equifax, Medtronic), `Location_Country` (HP, Abbott), `Country` (Baxter), `locations` (Intel, HPE, Thermo Fisher), `locationHierarchy1` (Philips), `Country_and_Jurisdiction` (Citi). `find_country_facet` recorre el árbol de facetas y prefiere el parámetro que contenga "country".
- `total` solo es confiable en la primera página; se toma de ahí.
- `locationsText` puede decir `"2 Locations"`: si se aplicó la faceta de país, se le agrega `| <país>`.
- `bulletFields[0]` suele ser el ID de requisición; se usa como `ats_job_id` junto con el tenant.
- Algunas empresas devuelven **422** o **404** cuando el `site` adivinado no es el correcto. Hay que copiar la URL real desde su página de empleos y probarla con `probe_workday.py`.
- Algunas empresas no tienen faceta para el país: en ese caso se busca por texto con el nombre del país y deciden los filtros de ubicación.
