# Candidate Notes

Fill this in as you work. We will use it as the starting point for the sync technical interview -- keep it short and focused, enough to anchor the conversation.

## Technical decisions

Use openAI por comodidad pero creé una abstracción, tal que la llamada no dependa del provider, si quiero agregar un provider distinto simplemente expando la abstracción.

K: Para esta data pequeña usar 3 me parece suficiente, ya que usar un valor muy alto podría introducir ruido de documentos que no deseo. En caso de mayor data podría usar 5, 10 o más. Considero que no hay un valor "perfecto" y se puede ir iterando hasta lograr un buen resultado.

Estoy poniendo el contexto en el user prompt, ya que es data que puede cambiar entre requests. Incluso algún fragmento podría tener data maliciosa y hacer prompt injection. Este user prompt incluye los documentos relevantes en orden y luego la pregunta del usuario:

```
"""Context documents:
[1] Title: Documento 1
Contenido del documento 1

[2] Title: Documento 2
Contenido del documento 2

Student question: {question}"""
```

_The main decisions you made and why. Examples: which LLM provider you used, how you modeled documents, how you designed the RAG prompt, which retrieval `k` you chose, whether you used an index on the vector column._

## Trade-offs and things left out

En un proyecto real y más grande hubiera hecho chunks del contenido y eso es lo que hubiera convertido a vector. Y esos vectores los hubiera almacenado en una tabla aparte de vectores. Incluso se podrían incluir metadatos en cada chunk antes de generar el vector. No lo hice por mantener la simplicidad de la prueba.

_Anything you deliberately skipped, simplified, or mocked, and why._

## What I would do next

Hacer mejor testing del search (testing con un llm).
Hacer chunking de los documentos.

_Two or three concrete things you would do if you had another half-day._
