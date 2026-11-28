# Vistas previas de las miniaturas

Al dejar el cursor un segundo sobre la miniatura de un video, en el inicio o en las recomendaciones de Play, se reproduce un preview corto: unos 10 s, en bucle y sin sonido. Abajo aparece una barra violeta de progreso y la duración sigue visible. Al quitar el cursor vuelve la miniatura.

En pantallas táctiles, con «Reducir movimiento» o con Ahorro de datos activado no se reproduce nada; la tarjeta funciona como antes.

## De dónde sale el preview

El preview es un **archivo propio guardado en S3**, generado una sola vez a partir del video original.

1. **Al generarlo.** FFmpeg lee el MP4 original en S3 mediante una URL firmada. No lo descarga completo: solo pide los rangos de bytes de cinco fragmentos de 2 s, tomados del 10 %, 30 %, 50 %, 70 % y 90 % del video. Los videos de menos de 12 s usan un único fragmento de hasta 10 s.
2. **Lo que produce.** Un MP4 nuevo a 360p, sin audio y con `faststart`, de unos 200–900 KB. Se guarda en `upload/previews/<id>.mp4` y su ruta queda en el campo `Videos.preview`.
3. **Al hacer hover.** El navegador descarga solo ese MP4 pequeño, con una URL firmada igual que las miniaturas. El video original no se toca.

En espacio son unos 0,5 MB por video: 1.000 videos ocupan unos 500 MB más en S3.

## Cuándo se genera

| Caso | Qué pasa |
|---|---|
| Video nuevo (panel o Django Admin) | Se encola automáticamente en la cola `video_previews` y lo procesa el servicio `preview_worker`. |
| Se reemplaza el MP4 | Se retira el preview anterior y se encola uno nuevo. Mientras se genera, la tarjeta muestra solo la miniatura. |
| Se editan otros datos (título, categorías…) | El preview se conserva. |
| Se borra el video | Su preview se borra con el resto de archivos. |
| Videos que ya estaban en el catálogo | **No se generan solos.** Hay que ejecutar `generar_previews_videos` (ver abajo). |

El worker de previews es independiente del de correos, para que un preview largo no retrase los correos de registro o recuperación.

## Antes de desplegar: permisos de S3

Si el usuario o rol de AWS de SoplaX tiene permisos limitados por carpeta (por ejemplo, solo `upload/videos/*` y `upload/Miniaturas/*`), añade sobre `upload/previews/*`:

- `s3:PutObject`
- `s3:GetObject`
- `s3:DeleteObject`

Sin esos permisos, la generación falla al guardar. Si el permiso ya cubre todo el bucket, no hay que cambiar nada.

## Despliegue en la VPS

Requiere que estén integradas las migraciones `0009_videos_duracion_segundos` (duración) y `0010_videos_preview` (preview). Si PostgreSQL es externo, omite `--profile postgres` en todos los comandos.

### 1. Simular la reconstrucción y el arranque

```sh
docker compose --env-file .env.production --dry-run build web
docker compose --env-file .env.production --profile postgres --dry-run up -d --no-build --wait web worker preview_worker
```

### 2. Reconstruir y revisar el plan de migraciones

```sh
docker compose --env-file .env.production build web
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py migrate --plan
```

El plan debe listar solo `app.0009_videos_duracion_segundos` y `app.0010_videos_preview`.

### 3. Aplicar la migración y levantar los servicios

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py migrate --noinput
docker compose --env-file .env.production --profile postgres up -d --no-build --wait web worker preview_worker
```

Desde aquí, los videos nuevos ya generan su preview solos.

### 4. Simular los previews del catálogo existente

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py generar_previews_videos --dry-run
```

`--dry-run` solo lee la duración de cada MP4; no crea archivos ni escribe en la base. Muestra, por cada video, cuántos fragmentos tendrá su preview y los errores de lectura que encuentre. **Revisa esta salida antes de aplicar.**

### 5. Generar los previews por lotes

```sh
docker compose --env-file .env.production --profile postgres run --rm --no-deps web python manage.py generar_previews_videos --aplicar --limite 50
```

Repite el comando hasta que informe `Aplicado: 0 vistas previas creadas`. `--limite` acota cuántos videos se procesan en cada ejecución, para avanzar por tandas y poder pararlo. Cada video tarda unos segundos, según la red hasta S3.

El comando también completa la duración de los videos que no la tengan, así que no hace falta ejecutar aparte `completar_duraciones_videos`.

Si un video falla, el comando sigue con los demás, muestra el error de cada uno y termina con error. Los que sí se generaron quedan guardados, y una nueva ejecución reintenta solo los pendientes.

## Comprobaciones

- **En el sitio:** pasa el cursor sobre varias miniaturas del inicio y de las recomendaciones de Play.
- **Logs del worker:**

  ```sh
  docker compose --env-file .env.production logs --tail 100 preview_worker
  ```

- **Videos pendientes:** vuelve a ejecutar el paso 4; debe mostrar `Simulación: 0 vistas previas por crear`.

## Archivos relacionados

- `app/video_previews.py`: genera el preview, lo guarda y lo encola.
- `app/management/commands/generar_previews_videos.py`: genera los previews del catálogo existente.
- `app/migrations/0010_videos_preview.py`: campo `Videos.preview`.
- `static/js/app.js` y `static/css/components/cards.css`: reproducción al pasar el cursor.
- `compose.yaml`: servicio `preview_worker`.
