# SoplaX en producción con Docker

El servicio web ejecuta Django con Gunicorn y sirve los estáticos desde la imagen con WhiteNoise. Redis conserva la cola de correo en un volumen. El trabajador procesa esa cola y los videos y miniaturas se sirven desde S3.

## Configuración

Copia la plantilla y completa los valores en `.env.production`.

```sh
cp .env.production.example .env.production
python -c "from secrets import token_urlsafe; print(token_urlsafe(48))"
```

- Usa una clave nueva en `DJANGO_SECRET_KEY` y ajusta los dominios y el origen HTTPS a tu despliegue. Retira la clave publicada de todo entorno. La rotación invalida las sesiones y los enlaces firmados con esa clave.
- Configura el bucket y la región de S3. Activa el bloqueo de acceso público y concede a la identidad del contenedor acceso a los prefijos de videos y miniaturas. Usa credenciales del entorno si tu plataforma requiere claves de AWS. Las URLs de lectura se firman por una hora.
- Configura el servidor SMTP y sus credenciales. El perfil usa STARTTLS en el puerto 587 por defecto.
- Con MySQL de Compose, usa `DB_HOST=mysql` y define `DB_PASSWORD` antes de crear el volumen. Con una base externa, configura su host, puerto, base, usuario y contraseña.
- Escribe entre comillas simples los valores que contengan `$` para que Compose los lea literalmente.
- Mantén Redis, MySQL y el puerto interno del servicio web en redes privadas. La imagen usa un usuario sin privilegios y excluye los archivos `.env*` de su contexto.

## Arranque con MySQL de Compose

```sh
docker compose --env-file .env.production build web
docker compose --env-file .env.production --profile mysql up -d --wait mysql redis
docker compose --env-file .env.production --profile mysql run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.production --profile mysql up -d --no-build --wait web worker
```

Si usas MySQL externo, inicia Redis con `docker compose --env-file .env.production up -d --wait redis` y ejecuta la migración y el arranque con los comandos anteriores omitiendo `--profile mysql`. En una base existente, puedes revisar primero el plan con `python manage.py migrate --plan` en el contenedor web. Si el proveedor requiere una CA de MySQL, móntala en el contenedor y apunta `DB_SSL_CA` a esa ruta.

Una base MySQL nueva se inicializa con el esquema de Django y el catálogo vacío. Para crear una cuenta de administración, ejecuta `docker compose --env-file .env.production exec web python manage.py createsuperuser`.

## Base de datos con contenido

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

Si cambias `SOPLAX_WEB_PORT`, usa el mismo puerto en `proxy_pass`. La ruta `/healthz/` comprueba que Django puede consultar MySQL.

Si usas Cloudflare, configura [TLS Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/) y [restringe el origen](https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/) con el firewall y la autenticación del proxy. Restaura la IP del visitante en Nginx únicamente para conexiones de una red confiable de Cloudflare. Añade [límites WAF](https://developers.cloudflare.com/waf/rate-limiting-rules/) en las rutas de cuentas y administración según el plan de la zona. [Habilita caché solo para estáticos](https://developers.cloudflare.com/cache/troubleshooting/dynamic-content-and-login-issues/). Las [cargas grandes](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/) pueden requerir un canal de administración a S3 separado del tráfico de Cloudflare.

## Verificación y mantenimiento

Ejecuta `python manage.py check --deploy` con la configuración de producción. Activa HSTS para subdominios cuando todos sirvan HTTPS. El aviso sobre preload es esperado si el dominio aún no adopta esa política.

En pruebas, confirma que el navegador recibe cookies `Secure`, que el trabajador entrega enlaces cuando corresponde, que una cuenta de personal solo accede a los módulos asignados y que S3 permite reproducir un video con su URL firmada. Supervisa los códigos 429 y 503 y los fallos de correo. Configura los registros del proxy y de Gunicorn para omitir los tokens de confirmación y recuperación.

Programa `python manage.py clear_expired_registrations` y `python manage.py clearsessions` a diario en el contenedor web.
