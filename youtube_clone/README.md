# YouTube Creator Clone

Descarga todas las transcripciones de un canal de YouTube y crea un chat donde Claude responde como esa persona.

## Instalación

```bash
pip install yt-dlp anthropic chromadb
```

## Uso

### 1. Extraer el contenido del canal

```bash
python extract.py https://www.youtube.com/@NombreDelCanal
```

Esto crea la carpeta `channel_data/` con:
- `channel_meta.json` — nombre y descripción del canal
- `videos.json` — todos los videos con transcripciones

Tiempo estimado: ~1-3 minutos por cada 50 videos.

### 2. Chatear con el creador

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python chat.py
```

O apuntando a otra carpeta de datos:

```bash
python chat.py --data mi_canal_data
```

## Cómo funciona

```
canal de YouTube
      │
   yt-dlp          ← descarga transcripciones automáticas/manuales
      │
  videos.json
      │
  ChromaDB          ← indexa los chunks por similitud semántica
      │
  Claude API        ← responde usando los fragmentos más relevantes
      │
   chat CLI
```

Cuando haces una pregunta:
1. Se buscan los `TOP_K=8` fragmentos más relevantes en ChromaDB
2. Se inyectan como contexto en el prompt de Claude
3. Claude responde en el estilo y tono del creador

## Notas

- Funciona mejor con canales que tengan subtítulos (manuales o automáticos)
- Idiomas soportados: español primero, inglés como fallback
- El índice se construye solo la primera vez; es en memoria (se reconstruye cada sesión)
- Límite: 500 videos por canal (configurable en `extract.py`)
