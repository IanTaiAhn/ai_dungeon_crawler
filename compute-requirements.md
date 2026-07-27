# Compute requirements

Reference notes on the models, disk space, and minimum hardware needed to run the stack described in `ai-dungeon-master-project-plan.md` locally via Ollama.

## Models needed

| Role | Suggested model | Quant | Approx. disk size | Notes |
|---|---|---|---|---|
| DM (narrator) | Llama 3.1 8B or Qwen2.5 7B/14B | Q4_K_M | ~4.5–5GB (7-8B) / ~8-9GB (14B) | Quality > speed — runs once per turn |
| Player agent | Llama 3.2 3B or Qwen2.5 3B | Q4_K_M | ~2GB | Speed > depth — runs every turn, benchmark down to 1-3B if decisions get incoherent |
| Embeddings | `nomic-embed-text` | default | <1GB | Powers the lore RAG pipeline, cheap to run on CPU even on GPU rigs |

**Total disk for model weights:** ~15-20GB depending on which DM size is chosen.

## Minimum hardware

### CPU-only (no GPU)
- 16GB system RAM minimum
- Modern 8-core CPU with AVX2
- Expect ~3-8 tok/s on the 7-8B DM model; player agent (3B) will be faster. Playable, but narration will feel laggy.

### Recommended (GPU)
- NVIDIA GPU with **8GB+ VRAM** (e.g. RTX 3060 12GB) — fits the player-agent model resident, swaps the DM model in/out via Ollama's dynamic loading
- **12-16GB VRAM** if you want both models resident simultaneously without reload latency when switching between DM and player-agent turns
- Apple Silicon alternative: unified memory means a base M-series Mac with **16GB unified RAM** runs 7-8B Q4 models smoothly with no dedicated VRAM needed

## VRAM vs RAM (quick reference)

- **RAM** is system memory used by the CPU.
- **VRAM** (Video RAM) is physical memory soldered onto the GPU card, used by GPU-accelerated code (e.g. Ollama running a model on GPU). It is not "virtual" or disk-backed.
- If a model's weights don't fit in VRAM, Ollama falls back to running some/all layers on CPU using regular RAM instead — slower, but functional.
- Apple Silicon is the exception: unified memory means one physical RAM pool serves both CPU and GPU, so there's no separate VRAM chip to size.

## Other compute notes

- LangGraph, Pydantic, Chroma, and FastAPI are CPU-trivial — not a sizing factor next to the LLMs.
- Self-hosting **Langfuse** (open-source tracing, phase 6) adds its own docker-compose stack (Postgres + ClickHouse + Redis), roughly +2-3GB RAM overhead if run on the same box as the models. **LangSmith** avoids this since it's cloud-hosted.
