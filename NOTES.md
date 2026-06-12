# Design Notes

Running notes on the technical decisions behind this project — what I chose, why, and what I'd change. This began as a take-home exercise; these notes started as the interview write-up and I keep them as a design log.

## Technical decisions

**Provider abstraction.** I use OpenAI by default for convenience, but the calls go through an abstraction (`EmbeddingProvider` ABC for embeddings, a LangChain `BaseChatModel` for chat) so the application code doesn't depend on the provider. Adding a different provider means extending the abstraction, not touching callers. For chat I also wired an optional Anthropic fallback via LangChain's `.with_fallbacks(...)` — if the primary errors out, the secondary takes over.

**Retrieval `k`.** For this small dataset, returning ~3 documents feels like enough; a very high `k` would introduce noise from documents I don't actually want. With more data I'd raise it to 5, 10, or more. There's no single "perfect" value — it's something to iterate on until results look good.

**Where the context goes in the prompt.** I put the retrieved context in the *user* prompt rather than the system prompt, because it's data that changes between requests, and a fragment could even contain malicious content attempting prompt injection — keeping it out of the system prompt limits its authority. The user prompt lists the relevant documents in order, followed by the student's question:

```
Context documents:
[1] Title: Document 1
Content of document 1

[2] Title: Document 2
Content of document 2

Student question: {question}
```

**Agentic retrieval.** Rather than a single fixed search, the agent decides whether to retrieve at all, grades the relevance of what it gets back, and rewrites the query to retry when results are weak. Grading is cheap by default (score thresholds) and only falls back to an LLM grader for the ambiguous middle band, to keep cost down.

## Trade-offs and things left out

**Chunking.** In a real, larger project I'd chunk the content and embed the chunks (which is what I ended up doing here), store those vectors in a dedicated chunks table, and possibly attach metadata to each chunk before embedding. The current splitter is a reasonable default but not tuned per content type.

**No vector index.** Search is exact (no IVFFlat/HNSW). Fine for ~20 documents; the first thing to add before scaling.

**Cost optimization.** Relevance grading uses score thresholds first and only calls the LLM grader for borderline cases, to avoid an LLM call on every search.

## What I'd do next

- Better evaluation of search quality (e.g. an LLM-graded eval harness over a fixed question set).
- Tune chunking — size, overlap, and per-subject strategies.
- Add an ANN index on the embedding column.
- Hybrid retrieval (keyword + vector) and richer per-chunk metadata.

## 2026-06 — De challenge a "Ask your PDFs"

Transformé el proyecto en una app de portafolio: subes archivos reales (PDF, escaneos, Word, Excel, imágenes) y chateas con ellos a través del mismo loop agéntico. El diseño completo está en `docs/superpowers/specs/2026-06-10-ask-your-pdfs-design.md`; aquí va el porqué de las decisiones grandes.

**Sesiones-workspace en vez de auth.** Para una pieza de portafolio, un login es fricción pura: nadie que llega del CV va a crear una cuenta. Cada visitante recibe una sesión anónima que actúa como workspace aislado; todo (documentos, chunks, mensajes) cuelga de ella con `ON DELETE CASCADE` y un sweeper la borra tras 24h de inactividad. El TTL convierte la falta de auth en una propiedad y no en un hueco: los datos son efímeros por diseño, así que tampoco guardo los archivos originales (parse-and-discard, solo persisten los chunks). El costo: si pierdes el localStorage, pierdes el workspace. Aceptable para el caso de uso.

**Ingesta async con contrato de status.** Procesar un PDF escaneado puede tomar decenas de segundos; bloquear el upload era inviable. El endpoint valida, inserta `pending`, devuelve 202 y una tarea en background avanza `status/stage/progress` con commit por etapa para que el polling vea movimiento real. La parte interesante es Render free: el proceso se duerme y se reinicia, matando tareas en vuelo. En vez de fingir que no pasa, lo hice un estado honesto: al arrancar, una reconciliación marca todo lo que quedó en pending/processing como `failed/interrupted` — un error visible es infinitamente mejor que un spinner eterno. Un semáforo (2 concurrentes) y un tope de cola (10) protegen los 512 MB del contenedor.

**OCR con LLM de visión en vez de Tesseract.** Tesseract significa dependencias de sistema, peor calidad en layouts complejos y cero comprensión de tablas/figuras. gpt-4o-mini transcribe mejor, devuelve markdown estructurado y no engorda la imagen Docker. El costo se acota con caps (20 páginas OCR por doc, rate limit por IP): el peor caso son centavos. El bug real que me encontré: con páginas en blanco el modelo a veces se *rehúsa* ("I'm sorry, I can't…") en vez de devolver vacío, y esa disculpa acababa indexada como contenido. La solución fue un contrato explícito en el prompt — responder exactamente `NO_TEXT` — más un filtro (`clean_transcription`) que también atrapa las negativas. Lección: la salida de un LLM en un pipeline necesita contrato y validación, como cualquier otra API.

**Guardrails: fail-open en moderación, fail-closed en parsing.** Son riesgos distintos. Si la API de moderación se cae y bloqueo todo, tumbé el producto por una dependencia externa; mejor degradar con log y tag en la traza (las respuestas además se basan en los documentos del propio usuario y solo él las ve). En cambio, un parser que falla y deja un documento "listo" pero vacío es mentirle al usuario: ahí siempre `failed` explícito. El scan de inyección es regex conservador (solo en inglés, presupuesto de falsos positivos casi cero) porque es un trip-wire barato, no la defensa principal — esa es el framing de `<retrieved-content>` como datos no confiables en el system prompt.

**Grounding como anotación post-stream, no como bloqueo.** Verificar antes de emitir significaría retener la respuesta completa y duplicar la latencia percibida — matas el streaming, que es la mitad de la UX. En su lugar, un juez LLM compara la respuesta contra los chunks recuperados *después* del último token y emite un veredicto (`grounded`/`ungrounded`/`unverified`) como badge. El usuario ya leyó la respuesta, sí, pero ahora sabe cuánto confiar en ella. Para documentos propios, anotar > censurar.

**Langfuse opcional sin claves.** `get_langfuse_handler()` devuelve `None` si no hay claves y todo el código trata ese `None` como no-op estricto. Los tests no necesitan claves, el entorno local no necesita cuenta, y en producción basta setear dos env vars para tener trazas completas (agente → tool → grader → score de grounding). La observabilidad debe ser un enchufe, no un requisito.

**slowapi en memoria.** Con un solo proceso en Render, un rate limiter en memoria es *exacto* — Redis agregaría una pieza de infra para resolver un problema de coordinación que no tengo. Limitación documentada: se resetea al reiniciar. El detalle que sí importó: setear `FORWARDED_ALLOW_IPS` para que uvicorn honre `X-Forwarded-For` detrás del proxy de Render; sin eso, todo internet comparte el bucket de la IP del load balancer.

**Sin tenacity.** Estaba en el plan original, pero los SDKs de OpenAI/Anthropic ya traen reintentos con backoff exponencial configurables. Envolverlos con tenacity multiplica los reintentos (3×3 = 9 llamadas en el peor caso) y los timeouts dejan de significar lo que dicen. Preferí timeouts explícitos + `max_retries` del SDK en cada cliente.

**Frontend papel-y-tinta.** Quería que la landing explicara el pipeline (upload → parse/OCR → chunks → embeddings → loop del agente → respuesta) con scroll, y que la app no pareciera otro clon de ChatGPT en gris. El concepto editorial — papel cálido, tinta, sellos bermellón para los rechazos (rate limit, guardrail) — sale del dominio: documentos. Toda la comunicación con el backend pasa por `lib/` con una unión discriminada de eventos SSE como contrato tipado; los componentes nunca hacen fetch directo.

**Trade-offs que asumo.** Sigue sin haber índice ANN (búsqueda exacta; con sesiones de ≤20 docs no se nota). El sniffing de archivos es de plausibilidad, no validación — un zip basura pasa como .docx y es el parser quien debe fallar limpio. El scan de inyección solo cubre inglés. Y el rate limit por IP castiga a NATs corporativos. Todos son costos conscientes para el tamaño real del problema.
