## Endpoints

- `GET /v1/models`
- `POST /v1/images/generations`
- `POST /v1/images/edits`
- `POST /v1/images/variations`
- `GET /health`
- `GET /v1/images/files/<arquivo>` para `response_format=url`

## Ciclo de memória

Por padrão os jobs são serializados. Depois de baixar a imagem final do ComfyUI, o gateway executa no `finally`:

1. `GET /queue`;
2. se não houver job rodando ou pendente, `POST /free`;
3. envia `{ "unload_models": true, "free_memory": true }`.

Isso evita que uma requisição descarregue o modelo enquanto outra o utiliza.

## Qual FLUX está instalado?

### Checkpoint all-in-one

O checkpoint oficial all-in-one Schnell FP8 é carregado por `CheckpointLoaderSimple` e deve ficar em `models/checkpoints`.

```env
COMFYUI_MODEL_LAYOUT=checkpoint
COMFYUI_CHECKPOINT=flux1-schnell-fp8.safetensors
```

Seu volume atual atende esse layout:

```yaml
- ./models_cache:/home/user/ComfyUI/models/checkpoints
```

### Split/full

O `flux1-schnell.safetensors` full/split é carregado por `UNETLoader` e exige os text encoders e o VAE separados:

```env
COMFYUI_MODEL_LAYOUT=split
COMFYUI_UNET=flux1-schnell.safetensors
COMFYUI_CLIP_L=clip_l.safetensors
COMFYUI_T5XXL=t5xxl_fp8_e4m3fn.safetensors
COMFYUI_VAE=ae.safetensors
```

Estrutura:

```text
models/diffusion_models/flux1-schnell.safetensors
models/text_encoders/clip_l.safetensors
models/text_encoders/t5xxl_fp8_e4m3fn.safetensors
models/vae/ae.safetensors
```

Nesse caso monte o diretório `models` inteiro no container, não apenas `checkpoints`.

## Testes

### ComfyUI

```powershell
curl.exe http://127.0.0.1:8188/system_stats
curl.exe http://127.0.0.1:8188/models/checkpoints
```

Para split:

```powershell
curl.exe http://127.0.0.1:8188/models/diffusion_models
curl.exe http://127.0.0.1:8188/models/text_encoders
curl.exe http://127.0.0.1:8188/models/vae
```

### Gateway

```powershell
curl.exe http://127.0.0.1:8764/health
curl.exe -H "Authorization: Bearer local" http://127.0.0.1:8764/v1/models
```

### Geração

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/generations" `
  -H "Authorization: Bearer local" `
  -H "Content-Type: application/json" `
  -d "{\"model\":\"gpt-image-1\",\"prompt\":\"a glass castle under an aurora\",\"size\":\"1024x1024\",\"n\":1,\"response_format\":\"b64_json\"}" `
  -o response.json
```

### Edição

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/edits" `
  -H "Authorization: Bearer local" `
  -F "model=gpt-image-1" `
  -F "prompt=turn the sky into a dramatic aurora" `
  -F "image=@input.png;type=image/png" `
  -F "response_format=b64_json" `
  -o edit.json
```

### Edição com máscara

O caminho implementado usa o canal alpha do PNG. Áreas transparentes são tratadas como editáveis, coerentemente com a máscara de edição OpenAI e com a máscara retornada pelo `LoadImage` do ComfyUI.

```powershell
curl.exe -X POST "http://127.0.0.1:8764/v1/images/edits" `
  -H "Authorization: Bearer local" `
  -F "model=gpt-image-1" `
  -F "prompt=replace the masked object with a crystal relic" `
  -F "image=@input.png;type=image/png" `
  -F "mask=@mask.png;type=image/png" `
  -F "response_format=b64_json" `
  -o edit-mask.json
```

## Open WebUI

Se o gateway roda no Windows e o Open WebUI em Docker:

```text
Engine: OpenAI
Base URL: http://host.docker.internal:8764/v1
API key: local
Model: gpt-image-1
```

O Open WebUI atual chama `/images/generations` sobre essa base. O gateway devolve `b64_json` por padrão e também suporta `url`.
