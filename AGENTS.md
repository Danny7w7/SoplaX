# Instrucciones para SoplaX

## Frontend

Antes de iniciar cualquier tarea de frontend, lee completo el documento [SoplaX — System Design Rules](docs/system-design-rules.md) y aplica sus reglas. La lectura es obligatoria también para revisiones y cambios menores en plantillas, estilos, scripts, recursos visuales o dependencias del frontend.

## Cambios de datos o archivos en producción

El usuario ejecuta los comandos de producción directamente en la VPS. Para estos trabajos, prepara y valida el comando en un entorno aislado y entrega la instrucción de Docker Compose con `--dry-run`. Usa la salida que comparta el usuario para revisar el plan antes de indicarle la aplicación.

## Datos privados del sitio

No agregar a Git, incluir en commits ni subir a repositorios remotos los JSON de `seeds/`, dumps, bases de datos, medios u otros datos reales del sitio. Mantener los JSON de datos excluidos en `.gitignore`. Cuando un despliegue necesite uno, indicar al usuario el archivo y la ruta de destino para que lo transfiera directamente a la VPS mediante WinSCP; el usuario realiza esa transferencia.
