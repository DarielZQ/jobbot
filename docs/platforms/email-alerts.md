# Alertas por correo (Gmail, solo lectura)

LinkedIn, CompuTrabajo, Indeed y elempleo, más las confirmaciones de postulación.

**Estado:** disponible con el extra `gmail` (`uv sync --extra gmail`). Viene apagado: se activa con `email_alerts.enabled: true` en `targets.yaml`. La configuración de Google Cloud, `jobbot gmail-login` y la activación se explican en la [guía de inicio, sección 10](../getting-started.md#10-alertas-por-correo-opcional).

El preset `costa-rica-it` trae consultas para LinkedIn, CompuTrabajo, Indeed y elempleo; `remote-latam`, para LinkedIn, CompuTrabajo e Indeed. Los dos traen las consultas de confirmaciones.

## Cómo funciona

1. Los sitios de empleo te envían alertas a tu Gmail.
2. `jobbot discover` (y la corrida diaria) busca en tu Gmail **solo** esos correos, según las consultas de `targets.yaml: email_alerts`, de los últimos `lookback_days` días (14 por defecto).
3. Extrae título, empresa, ubicación y enlace de cada vacante, y les aplica los mismos filtros que al resto.
4. Tú postulas desde el enlace (modo asistido, ADR-005). JobBot **nunca** entra a LinkedIn, CompuTrabajo ni Indeed, y nunca abre los enlaces de rastreo de los correos.

**Permiso:** `gmail.readonly`. JobBot puede buscar y leer correos, pero **no** puede enviar, borrar, marcar como leído ni modificar nada. Solo procesa los correos que coinciden con las consultas configuradas.

Para revisar en cualquier momento cuántas alertas llegaron por sitio (solo lee encabezados):

```bash
uv run jobbot alerts-status
```

## Crear las alertas

**LinkedIn** (en la web o la app):

1. Busca cada término con tu ubicación (por ejemplo `Service Desk`, `IT Support`, `Help Desk`, `Soporte técnico`, `Technical Support`).
2. Activa **Alerta de empleo** con frecuencia **diaria** y notificación por **correo electrónico**.

**CompuTrabajo** (con tu cuenta):

1. Busca, por ejemplo, `soporte técnico`, `mesa de ayuda` y `help desk`.
2. En los resultados, usa **Crear alerta** o **Recibir ofertas por email**.

**Indeed** y **elempleo:** crea alertas desde sus búsquedas con la opción de recibirlas por correo.

## Validar el formato

Cuando lleguen las primeras alertas (normalmente al día siguiente):

```bash
uv run jobbot alerts-sample --feed linkedin
uv run jobbot alerts-sample --feed computrabajo
uv run jobbot alerts-sample --feed indeed
uv run jobbot alerts-sample --feed elempleo
```

- El comando guarda el correo más reciente en `data/email_samples/` (dentro de tu carpeta de datos) y muestra cuántas vacantes reconoce. `--limit N` guarda más de uno.
- **"Vacantes reconocidas: 0"** o títulos raros: el sitio cambió el formato y hay que ajustar el lector. Abre un issue **sin adjuntar el correo**: describe la estructura con datos inventados.
- **"No hay correos que coincidan":** revisa el remitente de la alerta en Gmail y ajusta `query` en `targets.yaml`.
- Las muestras contienen datos de tu correo: bórralas cuando ya no sirvan.

## Etiqueta en Gmail para todas las alertas (opcional)

Para que todas las notificaciones de empleo queden juntas, crea un filtro en Gmail **desde la computadora** (la app del celular no permite crear filtros):

1. En gmail.com, abre las **opciones de búsqueda** (a la derecha de la barra de búsqueda).
2. En **De**, pega:
   ```
   jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR computrabajo.com OR indeed.com OR elempleo.com OR getonbrd.com
   ```
3. **Crear filtro** → marca **Aplicar la etiqueta** → **Nueva etiqueta…** → nombre `Empleo` → **Crear**.
4. Opcional: marca **Omitir Recibidos (archivar)**, para que no llenen tu bandeja principal.
5. Marca **Aplicar también el filtro a las conversaciones coincidentes** → **Crear filtro**.

JobBot busca en **todo** tu correo, no solo en Recibidos, así que sigue leyendo las alertas archivadas. JobBot no puede crear ni cambiar filtros: su permiso es solo de lectura.

## Si no llegan las alertas de LinkedIn

Puede que tus alertas avisen solo por la app. Revisa:

1. **Que LinkedIn use este Gmail:** Configuración → Inicio de sesión y seguridad → Direcciones de correo electrónico. Si es otro correo, agrega este Gmail y márcalo como principal.
2. **Que las alertas manden correo:** Configuración → Notificaciones → Búsqueda de empleo → Alertas de empleo → activar **Correo electrónico**.
3. **Spam y Promociones:** busca "linkedin" en esas pestañas.

Cuando llegue la primera, corre `uv run jobbot alerts-sample --feed linkedin` para validar el lector.

## Particularidades por sitio

- **LinkedIn** (`email:linkedin`): primero lee la parte de texto, en bloques `título / empresa / ubicación / View job: <url>`. Si no hay texto, usa los enlaces `jobs/view/<id>` del HTML, con `default_location`. El ID de LinkedIn evita duplicados.
- **CompuTrabajo** (`email:computrabajo`):
  - Cada oferta es un enlace de redirección que trae la URL real codificada (`.../oferta-de-trabajo-de-<título>-en-<lugar>-<ID hex de 32>`) y el ID.
  - El texto de la tarjeta mezcla etiquetas ("Se precisa Urgente · Empleo destacado"), título, nota de la empresa, empresa, ubicación y salario. El lector corta el título donde terminan las palabras del slug de la URL y toma como empresa lo que queda entre la nota y la ubicación.
  - Muchos correos son **promociones** sin ofertas individuales (solo un botón "Ver oportunidades"); producen 0 vacantes, como corresponde.
  - Si la misma oferta llega en varios correos, se guarda la versión que trae empresa.
- **Indeed** (`email:indeed`):
  - La consulta excluye las confirmaciones de postulación (para no reingresar vacantes ya postuladas) y los códigos de inicio de sesión (para no guardarlos nunca en las muestras).
  - Si un enlace trae el ID de la vacante (`jk=`), se usa la URL canónica `viewjob?jk=…`.
  - Si solo hay enlaces de rastreo, JobBot **nunca los abre**. Título, empresa y ubicación salen del texto del correo (alerta diaria o vacante recomendada) y el ID se arma con esos tres datos, así que la misma vacante en varios correos se guarda una sola vez. El enlace guardado lo abre el usuario, no JobBot.
- **elempleo** (`email:elempleo`): enlaces `elempleo.com/cr/ofertas-trabajo/<slug>/<id>`, con el mismo ID que el listado directo. La consulta excluye por asunto las confirmaciones de postulación y de alerta creada, que no traen vacantes y solo gastan cuota de Gmail.

## Confirmaciones de postulación (ADR-018)

- **Fuente:** `email:postulaciones`. Lee los correos que confirman una postulación y marca esa vacante como postulada (`applied_by_email`). Las consultas están en `targets.yaml: email_alerts.confirmations`.
- **LinkedIn** ("se ha enviado tu solicitud a <empresa>"): la primera vacante del correo es la postulada, con su ID. Las "similares" no se tocan.
- **Indeed:** el correo trae título, empresa y lugar, sin ID de la vacante. Se marcan las pendientes con la misma empresa y título.
- **CompuTrabajo** ("Seguimiento de tu candidatura para el puesto de …"): solo el título, en el asunto. Se marca solo si hay una única pendiente de CompuTrabajo con ese título. Las vacantes del cuerpo son recomendaciones.
- **elempleo:** su confirmación no dice a qué vacante se postuló; no se usa.
- En el panel, la vacante aparece en Postuladas como "marcada por el correo de confirmación", con un botón **Deshacer**.

## Detalles técnicos

- **Fuentes:** `discovery/email_alerts.py` (alertas) y `discovery/applications.py` (confirmaciones). Cliente: `mail/gmail.py`, la API REST de Gmail a través de `HttpClient`, con un intervalo corto para `gmail.googleapis.com` (`settings.yaml: http.host_min_interval_s`).
- **Búsqueda:** `(<query>) newer_than:<lookback_days>d`, hasta `max_messages` correos.
- **Límites de Google:** Gmail a veces avisa del límite de uso con un 403 en vez de 429; JobBot lo reconoce por el motivo que trae la respuesta y reintenta con espera. Cualquier otro 403 es definitivo y se muestra con su motivo.
- **Sin descripción:** estas vacantes no traen descripción (no se visitan los sitios), así que los filtros de descripción no aplican. Revisa los requisitos al abrir el enlace.
- **Apagado y sin configurar:** con `enabled: false` (el valor de las plantillas) las fuentes de correo no corren. Con `enabled: true`, si falta el extra `gmail`, `gmail_credentials.json` o la autorización, se reportan como "sin configurar" con el motivo, y el resto funciona igual.
- **Credenciales:** `profile/private/gmail_credentials.json` y `profile/private/gmail_token.json`, dentro de tu carpeta de datos. Para revocar el acceso: <https://myaccount.google.com/permissions> → JobBot → Quitar acceso.
