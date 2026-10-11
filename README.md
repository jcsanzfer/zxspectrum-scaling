# Scaling monocromo en ZX Spectrum 128K

Prueba técnica con **un único sprite original de 64×64, 512 bytes**.
Se incluyen dos variantes para comparar CPU y memoria:

- **Caché, demo principal:** el Z80 genera 57 tamaños al arrancar, de
  16×16 a 128×128 en pasos de dos píxeles. La animación copia las imágenes
  a la pantalla oculta, sin volver a ejecutar el escalador.
- **Tiempo real, referencia:** conserva los 113 tamaños originales, con
  pasos de un píxel y consultas de tablas en cada dibujo.

## Ejecutar

Para probar la demo sin instalar herramientas, clona el repositorio y abre
`demo/scaling.sna` en un emulador compatible con snapshots de Spectrum
128K. Espera unos segundos con pantalla negra: el propio Z80 está preparando
la caché. `demo/scaling.tap` contiene la misma versión en cinta. Para comparar
con la versión anterior, abre `demo/realtime.sna` o carga `demo/realtime.tap`.
Estos archivos son las compilaciones validadas que acompañan al código fuente.

En el entorno cloud, con Python 3.12+, Git, Make y un compilador C++17:

```sh
bash tools/setup.sh
```

El script instala SjASMPlus fijado a un commit y el emulador de CPU de las
pruebas en `.venv`, compila y valida. Después:

```sh
make test PYTHON=.venv/bin/python SJASMPLUS=/workspace/tooling/sjasmplus/sjasmplus
```

En otro ordenador, con SjASMPlus 1.24.0 instalado:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make test PYTHON=.venv/bin/python SJASMPLUS=sjasmplus
```

La versión principal se genera en `build/cached/`; la referencia en `build/`:

- `scaling.sna`: snapshot **128K**; abrir con un emulador de Spectrum que
  admita este formato, por ejemplo Fuse o una versión compatible de ZEsarUX.
- `scaling.tap`: cinta para **Spectrum 128K**, con cargador BASIC y cuatro
  bloques de bancos. Cargar desde Tape Loader o con `LOAD ""`. No sirve en
  un Spectrum 48K; una ROM 48K sobre hardware 128K sí tiene la RAM necesaria.
- `timings.json`: medidas de las 113 escalas ejecutando el Z80 ensamblado.

En `build/cached/timings.json` se guardan las medidas de las 57 escalas
con caché y el coste de preparación. Ambas variantes se compilan y prueban
con `make test`.

La animación es automática y el borde permanece negro. No hay controles
ni juego. Se dibuja en la pantalla oculta y se intercambia con la visible
al llegar la interrupción vertical, una vez terminado el dibujo.

## Cómo funcionan las tablas

Esta sección describe el núcleo compartido y las medidas de la variante
en tiempo real. La preparación de caché usa el mismo núcleo.

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
antes de dibujar. El bit de pantalla visible se conserva en **todas** las
operaciones de paginación. No se bloquea la paginación. Los bancos 5 y 7
contienen las dos pantallas; el banco 2 contiene el código, sprite, plan
activo, caché, pila y tabla de interrupciones IM2. El banco 6 queda libre.
El generador comprueba límites de banco y tamaño del plan.

El núcleo usa automodificación para seleccionar el desplazamiento del
sprite en `LD A,(IX+d)`. Por tanto debe ejecutarse en RAM y no es reentrante;
la interrupción IM2 privada preserva AF y BC, intercambia pantallas cuando
hay un cuadro pendiente, habilita interrupciones y retorna.

## Caché generada al arrancar

`src/cached.asm` activa la variante con caché y `src/cache.asm` implementa
preparación, copia y borrado de bordes. El Z80 prepara todas las imágenes
desde el único sprite antes de comenzar la animación. **Python no genera
los sprites escalados**: el snapshot y la cinta contienen vacíos los bancos
reservados para ellos.

Los 57 planes ocupan **27.421 bytes** en los bancos 0 y 1. Las imágenes
resultantes ocupan **48.784 bytes**, incluyendo cabecera de ancho, relleno
para centrado y alineación a bloques de 16 bytes. Se empaquetan sin cruzar
límites de banco:

| Banco | Bytes de caché |
| --- | ---: |
| 3 | 16.384 |
| 4 | 16.352 |
| 6 | 16.048 |

Los 113 tamaños necesitarían **95.113 bytes solo en píxeles empaquetados**,
antes de cabeceras y alineación. No caben en un banco de 16 KiB ni junto
a todas las tablas y buffers de esta organización. El paso de dos píxeles
es el compromiso de esta prueba.

Como solo hay una ventana paginable en `0xC000`, no podemos acceder allí
a un banco de caché y al banco 7 simultáneamente. Se copia la imagen a un
buffer común de **2.064 bytes**, se pagina el banco 7 y se escribe la
pantalla oculta. Se usan bloques de `LDI` desenrollados y avance directo
entre filas del bitmap del Spectrum, sin recalcular cada dirección.

Se recuerda el tamaño anterior por separado para cada pantalla. Al crecer,
la imagen opaca sobrescribe el rectángulo antiguo. Al reducir, se borran
solo las franjas que quedan fuera del nuevo rectángulo; el relleno interior
se sobrescribe. Así se evita borrar 128×128 en cada cuadro.

La caché depende del contenido del sprite: cambiarlo exige prepararla de
nuevo. Los planes geométricos se reutilizan. La copia y el borrado incluyen
automodificación de operandos y tampoco son reentrantes.

Medidas de CPU para la animación completa con buffers alternos, incluyendo
copia al buffer común, paginación, copia a pantalla y borrado de franjas:

| Tamaño | Tiempo real anterior | Caché al crecer | Caché al reducir |
| --- | ---: | ---: | ---: |
| 16×16 | 31,71 ms | 1,37 ms | 3,38 ms |
| 32×32 | 50,44 ms | 2,94 ms | 6,31 ms |
| 48×48 | 81,43 ms | 5,10 ms | 9,83 ms |
| 64×64 | 95,57 ms | 7,84 ms | 13,91 ms |
| 96×96 | 137,17 ms | 15,09 ms | 23,88 ms |
| 128×128 | 129,07 ms | 24,70 ms | — |

No hay reducción desde un tamaño superior a 128. El peor caso de toda la
secuencia medida ocurre al reducir a 112×112: **29,75 ms**. La preparación
inicial cuesta **22.361.290 T-states, 6,30 s ideales**, una vez.
Estos tiempos excluyen contención, interrupciones, espera HALT y el resto
del bucle de animación; **no son FPS medidos en un Spectrum completo**.
La caché no garantiza 50 dibujos/s en todo el rango.

La demo trabaja con un sprite opaco, centrado, sin máscara ni recorte y
sobre fondo negro. La caché incorpora el desplazamiento de bits de ese
centrado: otra posición horizontal requiere desplazar bytes o preparar
otras alineaciones. El borrado de franjas está diseñado para esta animación
centrada, sin gestión de varios objetos. Almacenar el resultado no mejora
los escalones y aliasing del vecino más próximo.

## Sincronización y doble pantalla

Este protocolo se aplica a las dos variantes.

Sincronizar únicamente el comienzo del dibujo con `HALT` no basta: un
dibujo grande tarda varios cuadros de vídeo. El nuevo cuadro se prepara
completo mientras el anterior sigue visible. Así el barrido no puede
encontrar el sprite borrado o a medio dibujar.

Cuando es visible el banco 5, se dibuja en el banco 7 paginado en `0xC000`.
Cuando es visible el banco 7, se dibuja en el banco 5 en `0x4000`. El plan
se copia primero, y se vuelve a paginar el banco 7 antes de borrar/dibujar.
Solo se cambia el bit 3 de `0x7FFD` en la rutina IM2, ante una interrupción
de cuadro y con `flip_pending` activo. Las interrupciones que llegan durante
el escalado mantienen la pantalla anterior. El cambio sucede al inicio
del cuadro, antes de la zona visible, bajo la temporización normal del 128K.

La secuencia corta `DI`/solicitud/`EI`/`HALT` evita que la pantalla se
intercambie justo antes de entrar en espera y se pierda otro cuadro de vídeo.
Ambas pantallas se inicializan, incluidos sus atributos. El borde permanece
negro para que las marcas de perfilado no produzcan destellos.

## Medidas y límites

Las medidas siguientes corresponden a la variante en tiempo real.

T-states medidos en emulación de **CPU Z80**, a 3.546.900 Hz. La suma incluye
borrado de una región de 128×128, selección/copia del plan, paginación de
la pantalla oculta y renderizado;
excluye el bucle de animación, la espera HALT, interrupciones y la
contención de memoria/puertos de un Spectrum completo.

| Tamaño | T-states | Tiempo ideal por dibujo |
| --- | ---: | ---: |
| 16×16 | 112.489 | 31,71 ms |
| 32×32 | 178.899 | 50,44 ms |
| 48×48 | 288.837 | 81,43 ms |
| 64×64 | 338.983 | 95,57 ms |
| 96×96 | 486.539 | 137,17 ms |
| 128×128 | 457.807 | 129,07 ms |

El tiempo no aumenta de forma monótona: depende de cuántos nibbles
contribuyen a cada byte y de cuántas filas se pueden reutilizar. La escala
2× exacta resulta más favorable que algunas escalas intermedias.

Esto demuestra que el método funciona y cabe en 128K. Esta primera versión
genérica **no alcanza 50 dibujos por segundo**; en 128×128 su techo ideal
es de unos 7,7 dibujos/s, antes de contención y sincronización. No se han
medido tiempos en hardware real ni se ha probado aún la carga de la cinta
a través de la ROM de un emulador completo.

El remuestreo es vecino más próximo: en monocromo introduce aliasing al
reducir y escalones al ampliar. Un paso de un píxel de tamaño no implica
suavidad temporal ni antialiasing. El dibujo es opaco, sin máscara, y borra
una región fija de la pantalla oculta. La doble pantalla evita mostrar el
borrado y el dibujo parcial; no aumenta la frecuencia de dibujos. La
comprobación visual y de temporización en un emulador completo o hardware
real sigue pendiente.
No es todavía un motor para varios sprites ni reproduce las prestaciones de SEGA.

Las siguientes optimizaciones que conviene medir son: kernels por geometría
que eliminen la interpretación de descriptores, rutas directas para 1×/2×,
borrado de la huella anterior. Ninguna
de ellas exige almacenar sprites a distintos tamaños. Posición arbitraria,
recorte y transparencia requieren ampliar el prototipo.

## Validación

`tools/verify.py` ejecuta los bytes ensamblados y compara el bitmap completo
con una referencia independiente. Comprueba 1.808 dibujos: 113 tamaños,
ocho patrones y ambas pantallas, incluyendo tres sprites aleatorios con
semilla fija.
Verifica selección de bancos, copia del plan, direccionamiento no lineal
del Spectrum, bits de relleno, atributos y preservación de la pantalla
fuera de la región de dibujo. Además arranca desde el SNA generado y
comprueba 225 intercambios con IM2/HALT y ambos cambios de sentido. El
modelo conserva los bancos paginados y rechaza cualquier escritura en la
pantalla visible durante el dibujo. Se inyectan interrupciones durante el
renderizado, se comprueba que no muestran un cuadro incompleto y que cada
intercambio muestra el bitmap esperado. Esto valida el protocolo en la
emulación de CPU, sin modelar la ULA ni la contención del Spectrum.

`tools/verify_cached.py` comprueba **456 imágenes generadas por el Z80**
(57 tamaños y ocho sprites), **1.808 copias** en ambas pantallas y
**113 intercambios** arrancando desde el snapshot. Compara con la misma
referencia independiente, verifica relleno y límites de banco, preservación
de planes/caché, ausencia de restos al reducir, atributos y pantalla exterior.
Un breakpoint hace fallar las pruebas si la animación vuelve a llamar al
escalador. Mantiene las comprobaciones de pantalla visible e interrupciones.

La cinta se comprueba por estructura, checksums y contenido de los bloques;
eso **no valida** la reproducción de cinta ni su carga por la ROM.
