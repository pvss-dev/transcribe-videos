# 🎙️ Transcriptor

Transcreve áudio e vídeo com o [Whisper](https://github.com/openai/whisper), pela
linha de comando ou por uma interface web onde você arrasta o arquivo.

![tests](https://img.shields.io/badge/tests-55%20passing-brightgreen)

O arquivo enviado é processado no servidor e **apagado assim que a transcrição
termina** — fica só o texto.

> **Sem download do YouTube.** Versões anteriores baixavam vídeos direto de uma
> URL. Isso saiu: o YouTube bloqueia requisições vindas de IP de datacenter, e
> a função falhava em cerca de 7 de cada 8 vídeos quando hospedada. Para
> baixar, use [yt-downloader](https://github.com/pvss-dev/yt-downloader) na sua
> própria máquina e traga o arquivo para cá.

## Instalação

O venv é obrigatório, não opcional. Ative-o **antes** do `pip install`:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# Sem GPU NVIDIA? Instale o PyTorch CPU-only primeiro (~200 MB em vez de ~1 GB)
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements-transcribe.txt
```

> Se aparecer `error: externally-managed-environment`, o `pip` está rodando no
> Python do sistema em vez do venv (Debian/Ubuntu bloqueiam isso — PEP 668).
> Rode `source .venv/bin/activate` e tente de novo.

Requer **ffmpeg** no sistema, usado para converter qualquer formato ao WAV que
o Whisper espera:

```bash
sudo apt install ffmpeg     # Debian/Ubuntu
brew install ffmpeg         # macOS
```

## Interface web

```bash
python -m transcriptor.web              # http://127.0.0.1:8000
python -m transcriptor.web --port 3000
```

Arraste um arquivo para qualquer lugar da página, escolha o modelo e o idioma
(ou "detectar automaticamente"). O card mostra o progresso ao vivo — quanto do
áudio já foi transcrito — e ao terminar oferece o `.txt` e o `.srt`.

O progresso chega por Server-Sent Events, então a página pode ser recarregada
sem perder o que está em andamento. Cada visitante enxerga apenas as próprias
transcrições, separadas por cookie de sessão.

Há tema claro e escuro, no botão do canto superior direito.

## Linha de comando

```bash
transcribe aula.mp4                          # gera aula.txt
transcribe aula.mp4 transcricao.txt          # nome de saída explícito
transcribe podcast.mp3 --model turbo --srt   # legendas junto
transcribe entrevista.m4a --detect-language
```

| Modelo   | VRAM   | Velocidade | Quando usar                |
|----------|--------|------------|----------------------------|
| `tiny`   | ~1 GB  | ~10x       | testes rápidos             |
| `base`   | ~1 GB  | ~7x        | processamento rápido       |
| `small`  | ~2 GB  | ~4x        | **padrão, bom equilíbrio** |
| `medium` | ~5 GB  | ~2x        | alta qualidade             |
| `large`  | ~10 GB | 1x         | melhor qualidade           |
| `turbo`  | ~6 GB  | ~8x        | **rápido e quase tão bom** |

Sem GPU os modelos rodam na CPU — funcionam, só mais devagar. `turbo` não faz
tradução (`--translate`); para isso use `medium` ou `large`.

O modelo é baixado uma vez e fica em `~/.cache/whisper` (o `small` tem ~460 MB).

## Uso como biblioteca

```python
from transcriptor import TranscriptionConfig, TranscriptionService

def on_progress(p):
    if p.percent is not None:
        print(f"{p.percent:.1f}%")

service = TranscriptionService(
    TranscriptionConfig(whisper_model="small", language="pt"),
    on_progress=on_progress,
)

outcome = service.process("aula.mp4", write_srt=True)
if outcome.success:
    print(outcome.result.text)
    print("salvo em", outcome.transcript_path)
else:
    print("falhou:", outcome.error)
```

## Estrutura

```
transcriptor/
├── cli.py            # comando `transcribe`
├── config.py         # TranscriptionConfig, modelos do Whisper
├── converter.py      # conversão para WAV 16 kHz mono via ffmpeg
├── transcriber.py    # Whisper + progresso
├── service.py        # orquestra conversão -> transcrição -> arquivos
├── retention.py      # limpeza automática
├── cleanup_cli.py    # comando `transcriptor-clean`
└── web/
    ├── server.py     # rotas FastAPI + stream SSE
    ├── jobs.py       # fila de transcrições em threads
    └── static/       # index.html, style.css, app.js

tests/                # 55 testes, sem rede e sem carregar modelo
```

## Limpeza automática

Nada é apagado por padrão. Defina pelo menos um limite:

```bash
transcriptor-clean --days 7 --dry-run    # ver o que sairia
transcriptor-clean --days 7              # aplicar
transcriptor-clean --max-gb 2
```

Ou deixe o servidor varrer sozinho:

```bash
python -m transcriptor.web --retention-days 7 --retention-max-gb 2
```

A limpeza nunca segue symlinks e nunca toca em arquivos de transcrições em
andamento.

## Deploy

Há um `Dockerfile`, um `docker-compose.yml` e um pipeline de CI/CD com deploy
automático. Detalhes em **[DEPLOY.md](DEPLOY.md)**.

```bash
docker compose up -d
```

> **A aplicação não tem autenticação.** Quem alcança a porta enfileira
> transcrições na sua máquina. Num servidor público, o que segura a carga é o
> conjunto de rate limiting no proxy, cota por sessão e limite de concorrência.
> O `deploy/nginx/transcriptor.conf` traz um modelo com tudo isso, e o
> [DEPLOY.md](DEPLOY.md) explica o passo a passo.

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

A suíte não acessa a rede nem carrega modelo do Whisper: as chamadas são
substituídas por duplos de teste, então roda offline em segundos.

## Requisitos

- Python 3.10+
- ffmpeg
- openai-whisper + PyTorch

## Licença

MIT
