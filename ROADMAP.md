# Planes

Qué viene en JobBot. Las decisiones que ya se tomaron están en [`docs/decisions.md`](docs/decisions.md). Si quieres trabajar en algo de esta lista, abre un issue para coordinar.

## Hecho: primera versión pública

- [x] Carpeta de datos `JOBBOT_HOME` y `jobbot init --preset` con plantillas dentro del paquete.
- [x] Presets `costa-rica-it` y `remote-latam`, con el bloque `region`.
- [x] `jobbot grill setup-profile`: entrevista para llenar perfil y búsqueda.
- [x] Detectores de grill-me, pestaña Decisiones en el panel y `jobbot grill pendientes`.
- [x] Revisiones de CV por usuario en `profile/resumes/checks.yaml`.
- [x] Extras opcionales `gmail` y `resumes`.
- [x] Scripts de Windows en `scripts/windows/` y `scripts/run_daily.sh` para cron en Linux y macOS.
- [x] CI en Windows, Linux y macOS: `pytest`, `ruff` y escaneo de privacidad.

## Siguiente

- **Más presets de países.** Cada preset necesita su bloque `region`, reglas de ubicación y fuentes verificadas. Ver [`CONTRIBUTING.md`](CONTRIBUTING.md#agregar-un-preset).
- **Interfaz en inglés.** Traducir el panel, el informe HTML y los mensajes de la CLI, con el idioma elegido en `settings.yaml`.
- **Modelo de lenguaje opcional para grill-me.** Redactar mejor las preguntas o resumir anuncios, activado solo si el usuario define `LLM_PROVIDER` y `LLM_API_KEY` en su `.env`. Las reglas deterministas siguen siendo el comportamiento por defecto, y el modelo nunca podrá escribir datos del perfil sin confirmación.
- **Más formatos de correo.** Alertas y confirmaciones de otros sitios e idiomas, y ajustes cuando los sitios actuales cambian su diseño.

## Ideas

- Reporte semanal del embudo: descubiertas → postuladas → respuestas → entrevistas.
- Notificaciones de escritorio en Linux y macOS.
- Más fuentes con API pública y términos que permitan este uso.

## Fuera de alcance

- Postular automáticamente o llenar formularios por el usuario.
- Evadir CAPTCHAs o protecciones anti-bot.
- Un servicio en la nube o cuentas de usuario.
