# Seguridad

## Cómo reportar una vulnerabilidad

**No abras un issue público** para un problema de seguridad.

Repórtalo en privado con los avisos de seguridad de GitHub:

1. En la página del repositorio, entra a la pestaña **Security**.
2. Haz clic en **Report a vulnerability**.
3. Describe el problema: qué versión o commit usas, sistema operativo, pasos para reproducirlo y qué impacto tiene.

No incluyas datos reales tuyos ni de nadie (correos, tokens, contenido de tu carpeta de datos). Si hace falta un ejemplo, usa datos inventados.

Los mantenedores confirmarán que recibieron el reporte, investigarán y publicarán la corrección junto con un aviso. Si quieres, se te reconoce en el aviso.

## Versiones con soporte

Solo la versión más reciente de la rama principal recibe correcciones de seguridad. Actualiza con `git pull` y `uv sync`.

## Qué datos maneja JobBot

JobBot corre solo en tu computadora. No tiene servidor, cuentas ni telemetría. Todo lo que guarda está en tu carpeta de datos (`JOBBOT_HOME`, por defecto `C:\Users\<Usuario>\JobBot` o `~/JobBot`):

| Dato | Dónde | Sensibilidad |
| :--- | :--- | :--- |
| Contacto, salario esperado | `profile/private/contact.yaml`, `compensation.yaml` | Alta |
| Credencial y token de Gmail | `profile/private/gmail_credentials.json`, `gmail_token.json` | Alta: dan acceso de lectura a tu correo |
| Valores privados | `.env` | Media |
| Experiencia, habilidades, CV | `profile/facts.yaml`, `answers.yaml`, `resumes/` | Media |
| Vacantes, postulaciones, decisiones | `data/jobbot.db` | Media |
| Muestras de correos de alerta | `data/email_samples/` | Media: bórralas cuando ya no sirvan |
| Informes y registros | `data/reports/`, `data/logs/` | Baja; los registros no deben contener datos personales |

Protege esa carpeta como protegerías tus documentos personales, y ten cuidado con dónde guardas sus respaldos.

## Medidas de diseño

- **Panel local:** escucha solo en `127.0.0.1`, exige su propio `Host` (contra DNS rebinding), acepta acciones solo como POST JSON desde su propio `Origin` (contra CSRF), no envía cabeceras CORS, no carga recursos de CDNs, inserta los datos de las vacantes como texto (nunca como HTML) y se apaga solo tras 10 minutos sin uso.
- **Gmail:** es un extra opcional y viene apagado (`email_alerts.enabled: false`). Cada usuario crea su propio cliente OAuth y autoriza solo `gmail.readonly`. JobBot no puede enviar, borrar ni modificar correos. El acceso se revoca en <https://myaccount.google.com/permissions>.
- **Red:** JobBot solo consulta las fuentes configuradas en `targets.yaml` (menos las de `disabled_sources`) y Gmail si lo activas. Nunca abre los enlaces de rastreo de los correos. Su `User-Agent` es `JobBot/<versión> (job search tool; contact: <JOBBOT_CONTACT_EMAIL>)`; el correo de contacto es opcional.
- **Sin postulaciones:** JobBot nunca envía formularios ni datos a empleadores.
- **Cambios a tus archivos:** la entrevista de grill-me muestra cada cambio y pide confirmación antes de escribir. Las decisiones de la corrida diaria solo aplican la opción que elijas.
- **Repositorio:** CI corre `scripts/privacy_scan.py` para que ningún archivo versionado contenga correos reales, rutas de usuario ni firmas automáticas. Cada colaborador puede sumar su lista de términos personales con `--denylist`, guardada fuera del repositorio.

## Fuera de alcance

- Vulnerabilidades que requieren que alguien ya tenga acceso a tu sesión de usuario o a tu carpeta de datos.
- Problemas en los sitios de empleo o en Google; repórtalos a cada proveedor.
