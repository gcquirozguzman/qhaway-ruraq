## Formato de salida (obligatorio)

Si el material enseña varias tareas, crea un procedimiento SEPARADO por tarea.
Separa cada procedimiento con una línea que contenga exactamente:

<!-- PROCEDIMIENTO -->

No escribas nada antes del primer procedimiento ni después del último.
Cada procedimiento debe seguir EXACTAMENTE esta plantilla Markdown:

# <Título de la tarea, en infinitivo. Ej: "Crear un usuario en la Consola del administrador">

> **Cuándo usar:** <una sola frase que diga en qué situación aplica este procedimiento>

## Objetivo
<qué logra la tarea y para qué sirve, 1-3 frases>

## Plataforma y URL de inicio
- **Plataforma:** <nombre del producto, ej. Google Workspace Admin>
- **URL de inicio:** <URL exacta, o "(no visible en el material)">

## Requisitos previos
- <permisos/rol necesario>
- <cuenta o sesión iniciada>
- <datos que hay que tener a mano>

## Pasos
1. **<Acción concreta en imperativo>**
   - **Elemento:** "<texto EXACTO del botón/menú/campo tal como aparece en pantalla>" (<tipo: botón, menú, campo, pestaña, casilla, enlace> — <ubicación en pantalla>)
   - **Valor a ingresar:** <solo si aplica>
   - **Resultado esperado:** <qué debería verse después de la acción>
   - **Video:** [mm:ss]
2. ...

## Errores comunes y advertencias
- <error, advertencia o buena práctica mencionada; si no hay, escribe "Ninguno mencionado.">

## Resultado esperado
<estado final verificable: qué se ve en pantalla o qué cambió en la plataforma>

## Reglas
- Un paso = una acción en la interfaz (clic, escribir, seleccionar, esperar). No agrupes varias.
- Copia literalmente el texto de la interfaz, respetando mayúsculas e idioma de la pantalla
  (si la interfaz está en inglés, usa el texto en inglés y añade la traducción entre paréntesis).
- Los timestamps en formato [mm:ss] (o [h:mm:ss] si pasa de una hora) indican dónde se ve
  ese paso en el material. Si no hay video, omite la línea "Video".
- Omite saludos, teoría general y conversaciones que no sean pasos de la tarea, salvo
  advertencias útiles (van en "Errores comunes y advertencias").
- Si el instructor menciona variantes (ej. "si es un usuario externo, en vez de esto..."),
  inclúyelas como sub-viñetas "**Variante:**" dentro del paso correspondiente.
- Usa los datos de ejemplo del material solo como ejemplo; marca con <corchetes angulares>
  los valores que el usuario debe reemplazar.
