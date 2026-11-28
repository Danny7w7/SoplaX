# SoplaX en producción con Docker

El servicio web ejecuta Django con Gunicorn y sirve los estáticos desde la imagen con WhiteNoise. Redis conserva la cola de correo en un volumen. El trabajador procesa esa cola y los videos y miniaturas se sirven desde S3.

## Configuración

Crea `.env.production` con `DJANGO_ENV=production` y genera la clave para `DJANGO_SECRET_KEY`.

```sh
python -c "from secrets import token_urlsafe; print(token_urlsafe(48))"
```

- Configura `DJANGO_ALLOWED_HOSTS` y `DJANGO_PUBLIC_BASE_URL` con los dominios y el origen HTTPS del despliegue. Retira la clave de Django publicada de todo entorno. La rotación invalida las sesiones y los enlaces firmados con esa clave.
- Define `AWS_STORAGE_BUCKET_NAME` y `AWS_S3_REGION_NAME`. Activa el bloqueo de acceso público y concede a la identidad del contenedor acceso a los prefijos de videos y miniaturas. Si tu plataforma requiere claves, define `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`. Las URLs de lectura se firman por una hora.
- Define `EMAIL_HOST`, `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD`. El perfil usa STARTTLS en el puerto 587 por defecto.
- Define `DB_HOST`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`. Con PostgreSQL de Compose, usa `DB_HOST=postgres` y `DB_PORT=5432`. Para una instancia externa, indica su host y puerto.
- Escribe entre comillas simples los valores que contengan `$` para que Compose los lea literalmente.
- Mantén Redis, PostgreSQL y el puerto interno del servicio web en redes privadas. La imagen usa un usuario sin privilegios y excluye los archivos `.env*` de su contexto.

Si usas un archivo distinto de `.env.production`, indica la misma ruta en `--env-file` y `SOPLAX_ENV_FILE`. Compose usa el primero para interpolar los valores de `compose.yaml` y el segundo para cargar el entorno de `web` y `worker`. Puedes definir `SOPLAX_ENV_FILE` dentro del archivo que pases con `--env-file`.

Al ejecutar Django directamente con `DJANGO_ENV=production` en el entorno del proceso, se carga `.env.production`. En ese caso, define también `REDIS_URL` con la conexión a Redis.

## Arranque con PostgreSQL de Compose

```sh
docker compose --env-file .env.production build web
docker compose --env-file .env.production --profile postgres up -d --wait postgres redis
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.production --profile postgres up -d --no-build --wait web worker
```

Si usas PostgreSQL externo, inicia Redis con `docker compose --env-file .env.production up -d --wait redis` y ejecuta la migración y el arranque con los comandos anteriores omitiendo `--profile postgres`. En una base existente, puedes revisar primero el plan con `python manage.py migrate --plan` en el contenedor web. Si el proveedor requiere una CA, monta el certificado en `web` y `worker`. Móntalo también en `seed` cuando importes el catálogo. Apunta `DB_SSL_CA` a la ruta dentro de los contenedores. Django usa esa CA para verificar el certificado y el nombre indicado en `DB_HOST`.

El servicio de Compose guarda los datos de PostgreSQL 18 en el volumen `postgres_data` montado en `/var/lib/postgresql`. Las migraciones de Django crean el esquema en una base nueva con el catálogo vacío. Para crear una cuenta de administración, ejecuta `docker compose --env-file .env.production exec web python manage.py createsuperuser`.

Ejecuta las migraciones y `createsuperuser` únicamente contra la instancia PostgreSQL destinada a SoplaX.

## Importar el catálogo de videos

En el equipo que tiene el catálogo local, activa el entorno virtual y genera el archivo desde SQLite con PowerShell.

```powershell
$env:DJANGO_ENV = "development"
New-Item -ItemType Directory -Path seeds -Force | Out-Null
python -X utf8 manage.py dumpdata app.actor app.categoria app.idioma app.postura app.videos --indent 2 --output seeds/catalogo.json
```

Django usa `db.sqlite3` salvo que hayas definido `DJANGO_SQLITE_PATH`. El archivo contiene metadatos, clasificaciones y claves de los videos y miniaturas en S3. Colócalo en `seeds/catalogo.json` junto a `compose.yaml` en el servidor, con permisos de lectura para el usuario del contenedor.

Ejecuta las migraciones y el seed únicamente contra el PostgreSQL asignado a SoplaX. Verifica el destino en `DB_HOST` y `DB_NAME`, y usa el bucket que ya contiene los videos y miniaturas en `AWS_STORAGE_BUCKET_NAME`. Con PostgreSQL en marcha, reconstruye la imagen, aplica las migraciones y simula la importación.

```sh
docker compose --env-file .env.production build web
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.production --profile postgres run --rm --no-deps seed
```

La simulación valida el archivo, consulta el catálogo y muestra cuántos videos insertaría y cuántos ya existen. Cuando el resultado sea el esperado, aplica la importación.

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps seed --aplicar
```

El seed usa la clave del objeto de S3 para identificar los videos, conserva los registros y las visitas existentes y enlaza las clasificaciones de los videos nuevos por nombre. Después de aplicar, repite la simulación y verifica que indica cero videos y cero clasificaciones por insertar.

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps seed
```

Con PostgreSQL externo, omite `--profile postgres`. Si el despliegue usa otro archivo de entorno, conserva su ruta en `--env-file` y `SOPLAX_ENV_FILE`.

## Organizar miniaturas en S3

Las miniaturas nuevas solo aceptan WebP y se guardan en `upload/Miniaturas/Premium/` o `upload/Miniaturas/NoPremium/`. La migración `0008_segmentar_miniaturas_premium` cambia la ruta de futuras cargas, pero no mueve archivos ni reescribe las claves que ya están guardadas. Para corregir referencias antiguas como `upload/photos/...`, el comando `convertir_miniaturas_webp --solo-legadas` crea las WebP segmentadas, actualiza las referencias de `Videos.miniatura` y retira las fuentes de S3 solo cuando ningún video las usa.

Antes de migrar, confirma que `DB_HOST` y `DB_NAME` apuntan exclusivamente al catálogo de SoplaX y que `AWS_STORAGE_BUCKET_NAME` es su bucket de medios. No ejecutes este procedimiento contra la base de producción del SWA.

Reconstruye la imagen, aplica las migraciones pendientes y genera el plan de solo lectura. Estos comandos consultan la base de datos y descargan los archivos desde S3 para inspeccionarlos; `--dry-run` no escribe en la base ni en S3.

```sh
docker compose --env-file .env.production build web
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py convertir_miniaturas_webp --solo-legadas --dry-run
```

El plan muestra cada ID, clave origen y destino exacto, tamaño, referencias compartidas y fuentes que retiraría. Convierte imágenes JPG/PNG antiguas, conserva WebP válidas y retira las claves `upload/photos/...` solo cuando ya no están referenciadas por un video o una miniatura. Comparte la salida completa del `--dry-run` para revisar las claves y los objetos que se retirarían antes de indicar la aplicación.

Después de revisar y aprobar el plan para el catálogo correcto, aplica la reubicación y vuelve a simular para confirmar que no quedan referencias a la ruta heredada:

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py convertir_miniaturas_webp --solo-legadas --aplicar
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py convertir_miniaturas_webp --solo-legadas --dry-run
```

La segunda simulación debe mostrar cero referencias por reubicar. Si PostgreSQL es externo, omite `--profile postgres`. No ejecutes `--aplicar` contra la base de producción del SWA.

## Espacios publicitarios de Play

Con `DJANGO_ENV=development` y `SOPLAX_PLAY_AD_PREVIEW=1`, Play muestra espacios de prueba sin solicitar creativos. En producción, cada variante se activa con `SOPLAX_PLAY_ADS`. La variable acepta un objeto JSON que contiene la posición, el dispositivo (`desktop` o `mobile`) y los campos `enabled`, `format` y `url`. Usa `enabled: true` y la URL HTTPS del iframe suministrado por el proveedor.

| Posición | Escritorio desde 70 rem | Móvil y tablet |
| --- | --- | --- |
| `PLAY_TOP_BANNER` | `970x90` o `728x90` | `320x50` o `320x100` |
| `PLAY_SIDEBAR_AD_1`, `PLAY_SIDEBAR_AD_2`, `PLAY_SIDEBAR_AD_3` | `300x250` o `300x600` | `300x250` tras los videos 3, 8 y 11 de recomendados, respectivamente |
| `PLAY_BOTTOM_AD_1` | `300x250` | `300x250` debajo de la información |
| `PLAY_BOTTOM_AD_2`, `PLAY_BOTTOM_AD_3` | `300x250` | — |
| `PLAY_RECOMMENDED_NATIVE` | `native`, 16:9 flexible tras el quinto video recomendado | `native`, 16:9 flexible tras el quinto video recomendado |

Para previsualizar la columna de dos anuncios de `300x600` y `300x250`, activa la vista de desarrollo y configura el primer lateral en `300x600` y el tercero con `enabled: false`.

```dotenv
SOPLAX_PLAY_AD_PREVIEW=1
SOPLAX_PLAY_ADS='{"PLAY_SIDEBAR_AD_1":{"desktop":{"enabled":true,"format":"300x600"}},"PLAY_SIDEBAR_AD_3":{"desktop":{"enabled":false}}}'
```

En producción se reserva el espacio de cada variante activa con formato y URL válidos. El iframe se crea cuando su formato cabe en el dispositivo y se acepta el aviso de edad. El navegador difiere la carga de los anuncios que quedan fuera de la vista, salvo el banner superior. El creativo debe admitir un iframe con sandbox. La política de seguridad autoriza sus orígenes únicamente en Play.

## Base de datos con contenido

Para pasar de MySQL a PostgreSQL, exporta los datos desde una copia de MySQL e impórtalos a una base PostgreSQL separada con el esquema de Django ya migrado. Valida la transferencia en pruebas antes del corte.

Si otro proceso está poblando la base, espera a que finalice y restaura una copia en un entorno de pruebas. Revisa `showmigrations` y `migrate --plan` contra esa copia. Compara las columnas, índices y relaciones de las tablas de SoplaX con la migración `0001_initial`, así como su historial en `django_migrations`. Usa `migrate --fake-initial` únicamente si la migración inicial no figura como aplicada y el esquema completo y las dependencias coinciden. Ante un historial incompatible, importa el contenido a un esquema nuevo ya migrado. Conserva los identificadores y hashes de usuarios, permisos y rutas de los objetos de S3.

Durante el corte, detén escrituras y toma una copia antes de migrar. La migración de correo se detiene ante duplicados. Resuélvelos en la copia identificando al titular de cada dirección. La migración elimina las contraseñas temporales y respeta el estado activo o suspendido de cada usuario.

## Proxy HTTPS

Compose publica el puerto en `127.0.0.1:8080`. Usa `DJANGO_TRUST_PROXY=1` cuando el acceso a Gunicorn esté limitado al proxy y este establezca las cabeceras. En el bloque HTTPS de Nginx, el ejemplo limita el cuerpo de las rutas públicas a 3 MiB. Sustituye `10.8.0.0/24` por la red de administración o aplica un control de acceso equivalente antes de admitir cargas grandes.

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Real-IP $remote_addr;

location ^~ /admin/ {
    allow 10.8.0.0/24;
    deny all;
    client_max_body_size 1g;
    proxy_read_timeout 300s;
    proxy_pass http://127.0.0.1:8080;
}

location / {
    client_max_body_size 3m;
    proxy_pass http://127.0.0.1:8080;
}
```

Si cambias `SOPLAX_WEB_PORT`, usa el mismo puerto en `proxy_pass`. La ruta `/healthz/` comprueba que Django puede consultar PostgreSQL.

Si usas Cloudflare, configura [TLS Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/) y [restringe el origen](https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/) con el firewall y la autenticación del proxy. Restaura la IP del visitante en Nginx únicamente para conexiones de una red confiable de Cloudflare. Añade [límites WAF](https://developers.cloudflare.com/waf/rate-limiting-rules/) en las rutas de cuentas y administración según el plan de la zona. [Habilita caché solo para estáticos](https://developers.cloudflare.com/cache/troubleshooting/dynamic-content-and-login-issues/). Las [cargas grandes](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/) pueden requerir un canal de administración a S3 separado del tráfico de Cloudflare.

## Verificación y mantenimiento

Ejecuta `python manage.py check --deploy` con la configuración de producción. Activa HSTS para subdominios cuando todos sirvan HTTPS. El aviso sobre preload es esperado si el dominio aún no adopta esa política.

En pruebas, confirma que el navegador recibe cookies `Secure`, que el trabajador entrega enlaces cuando corresponde, que una cuenta de personal solo accede a los módulos asignados y que S3 permite reproducir un video con su URL firmada. Supervisa los códigos 429 y 503 y los fallos de correo. Configura los registros del proxy y de Gunicorn para omitir los tokens de confirmación y recuperación.

Programa `python manage.py clear_expired_registrations` y `python manage.py clearsessions` a diario en el contenedor web.
