# Phase 2 — Mac Setup Runbook

To be executed the day the M-series MacBook arrives. Estimated total time: 2–4 hours.

---

## 0. Confirm specs

Before pulling models, confirm:

```bash
sysctl -n machdep.cpu.brand_string
sysctl -n hw.memsize | awk '{print $1/1024/1024/1024 " GB"}'
sw_vers
```

Decision rules based on RAM:

| Unified RAM | Recommended primary model | Fallback |
|---|---|---|
| 36 GB | Qwen 2.5 14B Q5 | Llama 3.1 8B Q5 |
| 48 GB | Qwen 2.5 14B Q5 + BGE-large embeddings | Mistral Small 22B Q4 |
| 64 GB | Qwen 2.5 32B Q4 | DeepSeek-Coder 33B for code-y reasoning |
| 96 GB | Qwen 2.5 32B Q5 + larger embeddings | Llama 3.3 70B Q3 (slow but possible) |
| 128 GB | Llama 3.3 70B Q4 or Qwen3-MoE quantized | Multiple models loaded simultaneously |

Update `docs/PRD.md § Assumed defaults` row "Mac specs" once confirmed.

---

## 1. Install Ollama

```bash
brew install ollama
ollama serve  # leave running in a screen / launchd service
```

Or grab the macOS .app from ollama.com — it auto-launches at login.

Pull the chosen primary model:

```bash
# Examples — pick one based on RAM
ollama pull qwen2.5:14b-instruct-q5_K_M
ollama pull qwen2.5:32b-instruct-q4_K_M
ollama pull llama3.3:70b-instruct-q4_K_M
```

And an embedding model:

```bash
ollama pull bge-large
# or
ollama pull nomic-embed-text
```

Smoke test:

```bash
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:32b-instruct-q4_K_M",
  "prompt": "Summarize Bitcoin in one paragraph. Cite no sources; this is a smoke test.",
  "stream": false
}'
```

Should return JSON in 2–10 seconds.

---

## 2. (Optional) Install MLX for ~2× throughput

MLX is Apple's native ML framework. Faster than llama.cpp/Ollama on Apple silicon for many models.

```bash
brew install python@3.12
python3.12 -m pip install mlx-lm
mlx_lm.generate --model mlx-community/Qwen2.5-32B-Instruct-4bit --prompt "Hi" --max-tokens 64
```

We'll add an `MLXProvider` (in `apps/api/app/agents/llm_provider.py`) once Ollama path is stable.

---

## 3. Tailscale

So the cloud-hosted backend can call the Mac.

1. Install: `brew install --cask tailscale`
2. Sign in to Tailscale, accept the device into your Tailnet.
3. Note the Mac's tailnet hostname: e.g., `dean-macbook.tail-abc123.ts.net`.
4. On your backend host (Fly.io / Railway / VPS), install Tailscale and join the same Tailnet. Fly has a [native integration](https://fly.io/docs/networking/tailscale/).

Test from the backend host:

```bash
curl http://dean-macbook.tail-abc123.ts.net:11434/api/tags
```

---

## 4. Expose Ollama beyond localhost (carefully)

By default Ollama binds to `127.0.0.1` — only the Mac itself can reach it. To accept Tailscale traffic:

```bash
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
# Then restart Ollama
```

Or in the Ollama app: Settings → Advanced → "Expose Ollama on the network".

**Important**: this binds to all interfaces. Tailscale is private (only your devices can reach it), but if the Mac is on a coffee-shop wifi without Tailscale ACLs, that port is exposed to the local network. Tighten with macOS firewall:

```bash
# Allow only Tailscale interface
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/ollama
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setapplication /usr/local/bin/ollama on
```

(Or set Tailscale ACLs to limit which devices can reach the Mac on port 11434.)

---

## 5. Wire backend to Mac

In `apps/api/.env` (or your hosting provider's env vars):

```
LLM_PROVIDER=routed
ROUTED_REASONING=ollama
ROUTED_EMBEDDING=ollama
ROUTED_FALLBACK=anthropic

OLLAMA_BASE_URL=http://dean-macbook.tail-abc123.ts.net:11434
OLLAMA_MODEL=qwen2.5:32b-instruct-q4_K_M
OLLAMA_EMBED_MODEL=bge-large
```

Restart the backend. The `OllamaProvider` will pick up the env, and the router will start sending reasoning/embedding traffic to the Mac.

---

## 6. Validate against the harness

```bash
cd eval
python hallucination_harness.py --provider ollama --report-out reports/ollama-baseline.md
python hallucination_harness.py --provider anthropic --report-out reports/anthropic-baseline.md
diff reports/ollama-baseline.md reports/anthropic-baseline.md
```

Acceptance criteria for promoting Ollama to default:

- Citation rate ≥95% (vs cloud baseline)
- No hallucinated numerical claims in regression cases
- Brief structure conformance ≥98%
- Calibration (where measurable) within 5pp of cloud baseline

If criteria miss, keep cloud as primary and tune prompts/models incrementally.

---

## 7. Operating considerations

- **Sleep behavior**: macOS sleep kills Ollama responsiveness. Either keep the Mac on 24/7 with display sleep allowed, or set `pmset -a sleep 0` (display can still sleep).
- **Power**: the Mac will draw more power under sustained inference. Plug it in.
- **Thermals**: M-series throttles when chassis is hot. Don't run it in a sealed bag. Rear vents clear.
- **Model swap**: use `ollama run <model>` to warm a model before peak hours; first-token latency drops dramatically.
- **Backup plan**: if the Mac goes offline, the routed provider falls back to Anthropic. You'll see a metric blip; the system keeps working.

---

## 8. Optional: move backend onto the Mac (full-local)

If you want zero cloud dependencies:

1. Install Postgres locally (or run via `infra/docker-compose.yml`).
2. Run FastAPI + Arq + Redis on the Mac.
3. Front it via Tailscale Funnel for HTTPS-from-anywhere, or keep the Next.js frontend on Vercel calling the Mac's tail-net hostname.

Trade-off: you stop paying Fly.io but you tie uptime to the Mac being on. For a private group of ≤10 this is fine; for anything serious, keep cloud-hosted backend with Mac as inference-only.

---

## 9. Day-1 checklist

- [ ] Mac unboxed, set up, on Wi-Fi
- [ ] Tailscale installed, joined Tailnet
- [ ] Ollama installed, primary model pulled
- [ ] Embedding model pulled
- [ ] Smoke test from Mac (curl localhost) ✅
- [ ] Smoke test from backend host (curl tailnet hostname) ✅
- [ ] Backend env vars updated
- [ ] Hallucination harness run, report saved
- [ ] PRD § Assumed defaults — Mac specs row updated with real RAM
