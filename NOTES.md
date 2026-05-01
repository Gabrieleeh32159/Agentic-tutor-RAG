# Candidate Notes

Fill this in as you work. We will use it as the starting point for the sync technical interview -- keep it short and focused, enough to anchor the conversation.

## Technical decisions

_The main decisions you made and why. Examples: which LLM provider you used, how you modeled documents, how you designed the RAG prompt, which retrieval `k` you chose, whether you used an index on the vector column._

## Trade-offs and things left out

En un proyecto real y más grande hubiera hecho chunks del contenido y eso es lo que hubiera convertido a vector. Y esos vectores los hubiera almacenado en una tabla aparte de vectores. Incluso se podrían incluir metadatos en cada chunk antes de generar el vector. No lo hice por mantener la simplicidad de la prueba.

_Anything you deliberately skipped, simplified, or mocked, and why._

## What I would do next

Hacer testing inteligente del RAG.

_Two or three concrete things you would do if you had another half-day._
