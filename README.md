# Scaling monocromo en ZX Spectrum 128K

Prueba técnica de escalado por tablas sobre **un único sprite de 64×64**
(512 bytes). La demo Z80 aumenta y reduce su tamaño entre **16×16 y
128×128**, de píxel en píxel. No hay versiones prerenderizadas del sprite.

## Ejecutar

Para probar la demo sin instalar herramientas, clona el repositorio y abre
`demo/scaling.sna` en un emulador compatible con snapshots de Spectrum
128K. `demo/scaling.tap` contiene la misma versión en formato cinta.
Estos archivos son la compilación validada que acompaña al código fuente.

En el entorno de desarrollo, con Python 3.12+, Git, Make y un compilador C++17:

```sh
bash tools/setup.sh
```

El script instala SjASMPlus fijado a un commit y el emulador de CPU de las
pruebas en `.venv`, compila y valida. Después:

```sh
make test PYTHON=.venv/bin/python SJASMPLUS=/workspace/tooling/sjasmplus/sjasmplus
```

Los resultados están en `build/`:

- `scaling.sna`: snapshot **128K**; abrir con un emulador de Spectrum que
  admita este formato, por ejemplo Fuse o una versión compatible de ZEsarUX.
- `scaling.tap`: cinta para **Spectrum 128K**, con cargador BASIC y cuatro
  bloques de bancos. Cargar desde Tape Loader o con `LOAD ""`. No sirve en
  un Spectrum 48K; una ROM 48K sobre hardware 128K sí tiene la RAM necesaria.
- `timings.json`: medidas de las 113 escalas ejecutando el Z80 ensamblado.

La animación es automática. El borde rojo marca borrado y copia del plan;
el verde, escalado y escritura. Negro indica espera de la siguiente
interrupción. No hay controles ni juego.

## Cómo funcionan las tablas

Para cada tamaño N se calcula una correspondencia de centros de píxel:

```text
origen(d) = floor((2*d + 1) * 64 / (2*N))
```

Una tabla vertical selecciona la fila original. El plan horizontal agrupa
los píxeles de cada byte de destino por su nibble de origen. Cada grupo
contiene el desplazamiento del byte original, la selección de nibble y una
tabla de **16 contribuciones de bits**. El Z80 consulta esas contribuciones
y las combina con OR para obtener el byte de destino.

Las tablas dependen de la geometría, **no del contenido del sprite**. Se
pueden cambiar los 512 bytes de `sprite` sin regenerarlas. Los tests hacen
exactamente eso con patrones aleatorios, píxeles aislados y otros casos.

Se reutiliza una fila ya escalada cuando dos filas consecutivas de destino
seleccionan la misma fila original. Esta caché mide 16 bytes y se invalida
en cada dibujo. El centrado horizontal incluye desplazamiento a nivel de
bit: no hay saltos de ocho píxeles al cambiar el ancho.

Los 113 planes ocupan **55.498 bytes**, almacenados en los bancos 0, 1, 3 y
4. La selección usa el puerto `0x7FFD`; se copia un plan a la RAM común
antes de dibujar. No se bloquea la paginación ni se selecciona la pantalla
alternativa. El banco 5 contiene la pantalla, el banco 2 el código, sprite,
plan activo, caché, pila y tabla de interrupciones IM2. Los bancos 6 y 7
quedan libres. El generador comprueba límites de banco y tamaño del plan.

El núcleo usa automodificación para seleccionar el desplazamiento del
sprite en `LD A,(IX+d)`. Por tanto debe ejecutarse en RAM y no es reentrante;
la interrupción IM2 privada únicamente habilita interrupciones y retorna.

## Medidas y límites

T-states medidos en emulación de **CPU Z80**, a 3.546.900 Hz. La suma incluye
borrado de una región de 128×128, selección/copia del plan y renderizado;
excluye el bucle de animación, la espera HALT, interrupciones y la
contención de memoria/puertos de un Spectrum completo.

| Tamaño | T-states | Tiempo ideal por dibujo |
| --- | ---: | ---: |
| 16×16 | 110.351 | 31,11 ms |
| 32×32 | 176.537 | 49,77 ms |
| 48×48 | 286.251 | 80,70 ms |
| 64×64 | 336.173 | 94,78 ms |
| 96×96 | 483.281 | 136,25 ms |
| 128×128 | 454.101 | 128,03 ms |

El tiempo no aumenta de forma monótona: depende de cuántos nibbles
contribuyen a cada byte y de cuántas filas se pueden reutilizar. La escala
2× exacta resulta más favorable que algunas escalas intermedias.

Esto demuestra que el método funciona y cabe en 128K. Esta primera versión
genérica **no alcanza 50 dibujos por segundo**; en 128×128 su techo ideal
es de unos 7,8 dibujos/s, antes de contención y sincronización. No se han
medido tiempos en hardware real ni se ha probado aún la carga de la cinta
a través de la ROM de un emulador completo.

El remuestreo es vecino más próximo: en monocromo introduce aliasing al
reducir y escalones al ampliar. Un paso de un píxel de tamaño no implica
suavidad temporal ni antialiasing. El dibujo es opaco, sin máscara, y borra
una región fija de la pantalla visible; puede mostrar parpadeo y tearing.
No es todavía un motor para varios sprites ni reproduce las prestaciones de SEGA.

Las siguientes optimizaciones que conviene medir son: kernels por geometría
que eliminen la interpretación de descriptores, rutas directas para 1×/2×,
borrado de la huella anterior y doble pantalla usando el banco 7. Ninguna
de ellas exige almacenar sprites a distintos tamaños. Posición arbitraria,
recorte y transparencia requieren ampliar el prototipo.

## Validación

`tools/verify.py` ejecuta los bytes ensamblados y compara el bitmap completo
con una referencia independiente. Comprueba 904 dibujos: 113 tamaños y
ocho patrones, incluyendo tres sprites aleatorios con semilla fija.
Verifica selección de bancos, copia del plan, direccionamiento no lineal
del Spectrum, bits de relleno, atributos y preservación de la pantalla
fuera de la región de dibujo. Además arranca desde el SNA generado y
comprueba 225 cuadros con IM2/HALT y ambos cambios de sentido.

La cinta se comprueba por estructura, checksums y contenido de los bloques;
eso **no valida** la reproducción de cinta ni su carga por la ROM.
