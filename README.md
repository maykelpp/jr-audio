# JR Audio · Control Center

Panel administrativo y API para comunicar el estado del servicio a la APK Android.

## Funciones

- Mantenimiento en modo **local**: la APK debe mantener la música descargada y desactivar únicamente funciones online.
- Aviso de actualización con versión, enlace HTTPS y notas.
- Aviso de nueva versión en preparación.
- Caducidad opcional por fecha/hora UTC para cada aviso.
- API pública de solo lectura y panel administrativo con sesión firmada + protección CSRF.
- PostgreSQL para persistir configuración.

## API

- `GET /healthz` — health check.
- `GET /api/v1/app-status` — estado público para la APK.
- `GET /` — panel administrativo.
- `GET /api/admin/csrf` — token CSRF.
- `POST /api/admin/login` — inicio de sesión.
- `GET /api/admin/status` — leer configuración (admin).
- `PATCH /api/admin/status` — actualizar configuración (admin).
- `POST /api/admin/logout` — cerrar sesión.

El endpoint público nunca expone datos de administración. La APK debe consultar al iniciar y al volver a primer plano, cachear la última respuesta válida y usar reintentos con espera incremental. Durante mantenimiento, debe seguir disponible la biblioteca local.

## Despliegue Render

1. El Blueprint `render.yaml` crea un Web Service Free y PostgreSQL Free en Ohio.
2. En la configuración inicial de Render, introduce un valor fuerte y único para `ADMIN_PASSWORD` cuando lo solicite.
3. Conserva `SECRET_KEY` generado por Render. No lo publiques ni lo pongas en la APK.
4. Después del primer deploy abre la URL `onrender.com`, inicia sesión con usuario `admin` y la contraseña configurada.

### Límites del plan Free

El Web Service puede suspenderse tras inactividad y tardar en responder al primer acceso. No existe garantía de disponibilidad continua mediante auto-ping. El PostgreSQL Free de Render es temporal y tiene límite de vida/recursos; no lo uses como único almacenamiento permanente de datos importantes. Antes de que expire, exporta la base de datos o migra a un plan persistente.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="cambia-esto-localmente"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="una-clave-local"
uvicorn app:app --reload
```

Abre `http://127.0.0.1:8000`.

## Contrato de estado para Android

Ejemplo resumido:

```json
{
  "app": "JR Audio",
  "api_version": 1,
  "maintenance": {"enabled": true, "mode": "local"},
  "update": {"available": false},
  "preparing": {"enabled": false}
}
```

No uses el estado de mantenimiento para cerrar el reproductor local ni borrar caché/descargas. La instalación de actualizaciones siempre debe requerir confirmación del usuario mediante el instalador Android.
