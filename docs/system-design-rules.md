# SoplaX — System Design Rules

## 1. Identidad de marca

SoplaX es una plataforma de entretenimiento para adultos cuya identidad visual debe transmitir modernidad, exclusividad, atrevimiento, elegancia y profesionalismo.

La interfaz debe tener una estética propia, inspirada en la calidad visual de las plataformas modernas de streaming, evitando imitar a Pornhub, XVideos, XNXX o xHamster.

La escritura oficial de la marca es **SoplaX**, respetando las mayúsculas y minúsculas.

## 2. Paleta de colores oficial

| Variable CSS | HEX | Uso |
| --- | --- | --- |
| `--color-background` | `#0D0B13` | Fondo principal |
| `--color-surface` | `#1B1625` | Tarjetas, menús y contenedores |
| `--color-primary` | `#8B5CF6` | Color corporativo |
| `--color-primary-hover` | `#A78BFA` | Estados hover |
| `--color-accent` | `#C4B5FD` | Acentos y elementos activos |
| `--color-text` | `#F5F3FF` | Texto principal |
| `--color-text-muted` | `#A1A1AA` | Texto secundario |
| `--color-border` | `#332B42` | Bordes y separadores |

Todos los colores deben centralizarse mediante variables CSS globales. No utilizar colores arbitrarios directamente en los componentes.

## 3. Proporcionalidad cromática

Aplicar la regla 75-20-5 como referencia de composición visual:

- 75%: fondos oscuros, principalmente negro obsidiana.
- 20%: superficies secundarias, grises, bordes y elementos neutros.
- 5%: violeta eléctrico y sus variantes.

Estas proporciones son orientativas y no deben calcularse literalmente por píxeles. No incluyen las imágenes ni las miniaturas del contenido.

El violeta debe utilizarse estratégicamente para destacar acciones, botones principales, navegación activa, enlaces relevantes y elementos de identidad corporativa.

No saturar la interfaz con el color corporativo.

## 4. Restricciones visuales

- No utilizar naranja, rojo, azul eléctrico o amarillo como colores corporativos.
- No utilizar negro puro como fondo predominante.
- No abusar de degradados, sombras, efectos neón o brillos.
- No utilizar bordes violetas en todos los componentes.
- No imitar la identidad gráfica de otras plataformas del sector.
- Se permiten colores semánticos para errores, advertencias y confirmaciones cuando sean necesarios.

## 5. Tipografía

Utilizar preferiblemente Inter, con una fuente sans-serif del sistema como alternativa.

La tipografía debe ser moderna, limpia y legible. Mantener una jerarquía visual coherente mediante tamaños, pesos y espaciados consistentes.

## 6. Componentes y distribución

- Diseño minimalista y funcional.
- Priorizar el contenido sobre los elementos decorativos.
- Mantener las miniaturas en una relación de aspecto 16:9.
- Utilizar bordes redondeados moderados, entre 6 y 12 píxeles.
- Mantener espaciados basados en múltiplos de 4 píxeles.
- Utilizar animaciones sutiles de entre 150 y 250 ms.
- Mantener consistencia entre botones, formularios, tarjetas, menús y ventanas modales.
- Garantizar un diseño completamente responsive y mobile-first.

## 7. Arquitectura frontend

No utilizar Bootstrap ni incorporar nuevamente esta dependencia.

Priorizar:

- HTML5 semántico.
- CSS3 nativo.
- CSS Custom Properties.
- CSS Grid.
- Flexbox.
- JavaScript nativo cuando sea necesario.
- Componentes reutilizables.

No incorporar nuevos frameworks frontend sin autorización explícita.

Mantener una arquitectura CSS modular, organizada, escalable y fácil de mantener.

Evitar estilos inline, duplicación de código y el uso innecesario de `!important`.

## 8. Accesibilidad y rendimiento

- Garantizar contraste adecuado entre fondos, textos y botones.
- Verificar el cumplimiento de WCAG 2.2 AA en los componentes.
- Mantener estados visibles de foco para navegación mediante teclado.
- Priorizar fuentes, recursos y dependencias ligeras.
- Evitar animaciones que afecten negativamente el rendimiento.
- Respetar la preferencia `prefers-reduced-motion` del usuario.
- Evitar desplazamientos horizontales en dispositivos móviles.

## 9. Logo e identidad futura

El logo definitivo será diseñado posteriormente.

La interfaz debe estar preparada para incorporar un logo basado en la identidad cromática oficial, donde la X pueda funcionar como elemento distintivo e independiente de la marca.

No generar ni establecer un nuevo logo definitivo sin autorización.

## 10. Cumplimiento

Toda nueva página, funcionalidad, componente o modificación visual debe respetar estas reglas.

No introducir decisiones de diseño que contradigan la identidad visual establecida sin autorización explícita.
