
### Responses versao moderna do /v1/chat/completions
POST   /v1/responses
GET    /v1/responses/{response_id}
DELETE /v1/responses/{response_id}

### Conversations
POST   /v1/conversations
GET    /v1/conversations/{conversation_id}
POST   /v1/conversations/{conversation_id}
DELETE /v1/conversations/{conversation_id}
POST   /v1/conversations/{conversation_id}/items
GET    /v1/conversations/{conversation_id}/items
GET    /v1/conversations/{conversation_id}/items/{item_id}
DELETE /v1/conversations/{conversation_id}/items/{item_id}

### Chat Completions
POST   /v1/chat/completions
GET    /v1/chat/completions
GET    /v1/chat/completions/{completion_id}
POST   /v1/chat/completions/{completion_id}
DELETE /v1/chat/completions/{completion_id}

GET    /v1/chat/completions/{completion_id}/messages

### Embeddings
POST   /v1/embeddings

### Files
POST   /v1/files
GET    /v1/files
GET    /v1/files/{file_id}
DELETE /v1/files/{file_id}
GET    /v1/files/{file_id}/content

### Vector Stores
POST   /v1/vector_stores
GET    /v1/vector_stores
GET    /v1/vector_stores/{vector_store_id}
POST   /v1/vector_stores/{vector_store_id}
DELETE /v1/vector_stores/{vector_store_id}

POST   /v1/vector_stores/{vector_store_id}/search

POST   /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files/{file_id}
POST   /v1/vector_stores/{vector_store_id}/files/{file_id}
DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}
GET    /v1/vector_stores/{vector_store_id}/files/{file_id}/content

POST   /v1/vector_stores/{vector_store_id}/file_batches
GET    /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}
POST   /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel
GET    /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files

### Moderations
POST   /v1/moderations

### Batches
POST   /v1/batches
GET    /v1/batches
GET    /v1/batches/{batch_id}
POST   /v1/batches/{batch_id}/cancel

### Fine-tuning
POST   /v1/fine_tuning/jobs
GET    /v1/fine_tuning/jobs
GET    /v1/fine_tuning/jobs/{fine_tuning_job_id}
POST   /v1/fine_tuning/jobs/{fine_tuning_job_id}/cancel
POST   /v1/fine_tuning/jobs/{fine_tuning_job_id}
GET    /v1/fine_tuning/jobs/{fine_tuning_job_id}/events

### Evals
POST   /v1/evals
GET    /v1/evals
GET    /v1/evals/{eval_id}
POST   /v1/evals/{eval_id}
DELETE /v1/evals/{eval_id}

POST   /v1/evals/{eval_id}/runs
GET    /v1/evals/{eval_id}/runs
GET    /v1/evals/{eval_id}/runs/{run_id}
POST   /v1/evals/{eval_id}/runs/{run_id}
DELETE /v1/evals/{eval_id}/runs/{run_id}
GET    /v1/evals/{eval_id}/runs/{run_id}/output_items

### Models
GET    /v1/models
GET    /v1/models/{model}
DELETE /v1/models/{model}

### Realtime
POST   /v1/realtime/client_secrets
POST   /v1/realtime/transcription_sessions
POST   /v1/realtime/translations

### Videos
POST   /v1/videos
GET    /v1/videos
GET    /v1/videos/{video_id}
POST   /v1/videos/{video_id}
DELETE /v1/videos/{video_id}

GET    /v1/videos/{video_id}/content

### Resumo prático
Se a sua intenção é **implementar uma API compatível com OpenAI**, como você provavelmente está fazendo para o seu ecossistema de IA/PIA, eu consideraria este conjunto como o núcleo de compatibilidade:

```text
POST /v1/chat/completions
POST /v1/responses

GET  /v1/models
GET  /v1/models/{model}

POST /v1/embeddings

POST /v1/audio/speech
POST /v1/audio/transcriptions
POST /v1/audio/translations

POST /v1/images/generations
POST /v1/images/edits

POST /v1/moderations

POST /v1/files
GET  /v1/files
GET  /v1/files/{file_id}
DELETE /v1/files/{file_id}
GET  /v1/files/{file_id}/content

POST /v1/batches
GET  /v1/batches
GET  /v1/batches/{batch_id}
POST /v1/batches/{batch_id}/cancel
```
