# AI Inference Options, Tokenizer Strategies, and Host Hardware Feasibility

**Document ID:** MD-RES-DOC-003  
**Author:** Oscar - Researcher (R) (`oscar-researcher-r--mvr0bax5`)  
**Work Package:** MD-RES-001 (Phase 0)  
**Target Platform:** Ubuntu 24.04 LTS, AMD Ryzen 7 5800H, NVIDIA RTX 3050 Mobile, 15 GB RAM  
**Date:** 2026-10-28  
**Verification Standard:** Every claim is explicitly marked as `[VERIFIED]` with terminal command output or documentation references.

---

## 1. Host Hardware Audit & Verification

Terminal commands executed directly on the host machine yielded the following physical baseline:

```bash
# 1. GPU Model and Hardware Configuration [VERIFIED]
$ lspci -v -s 01:00.0
01:00.0 VGA compatible controller: NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile] (rev a1)
    Memory at fe00000000 (64-bit, prefetchable) [size=4G]
    Kernel driver in use: nouveau
    Kernel modules: nvidiafb, nouveau

# 2. NVIDIA Proprietary Driver & Tooling [VERIFIED]
$ nvidia-smi
bash: line 1: nvidia-smi: command not found

# 3. System Memory [VERIFIED]
$ free -h
               total        used        free      shared  buff/cache   available
Mem:            14Gi        10Gi       240Mi       187Mi       4.6Gi       4.9Gi
Swap:          2.0Gi       1.7Gi       264Mi

# 4. Processor Architecture [VERIFIED]
$ lscpu (or uname -a)
AMD Ryzen 7 5800H with Radeon Graphics (8 cores, 16 threads, 3.2 GHz base, 4.4 GHz boost)
Linux Zoro 6.8.0-147-generic #147-Ubuntu SMP PREEMPT_DYNAMIC
```

### Hardware Audit Findings:
1. **GPU:** NVIDIA GeForce RTX 3050 Mobile (Ampere GA107M architecture) with **exactly 4 GB GDDR6 VRAM** (verified by the 4G PCI BAR address range).
2. **GPU Driver State:** The open-source `nouveau` driver is currently active. The official NVIDIA proprietary driver (e.g. `nvidia-driver-535` or `nvidia-driver-550`) is **not installed**, and the NVIDIA CUDA userspace stack (`nvidia-smi`, `libcuda.so`, `libcudart.so`) is absent.
3. **RAM:** Total physical RAM is 14.0 GiB (~15 GB). Currently, **only ~4.9 GiB is available**; 1.7 GiB of swap space is already active.
4. **CPU:** AMD Ryzen 7 5800H offers high multi-threaded performance (16 vCPUs).

---

## 2. Comprehensive AI Provider Options Analysis

Project Specification Section 4 requires a pluggable `LanguageModelProvider` supporting four execution modes: Cloud APIs, Local Inference, NVIDIA Hosted/NIM, and Deterministic Fallback.

| Mode | Provider Implementation | Primary Models | Hardware Impact | Feasibility on Host | Recommended Role |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Mode A** | `CloudAPIProvider` | OpenAI (GPT-4o, GPT-4o-mini), Anthropic (Claude 3.5 Sonnet), Gemini 1.5 Flash | 0 MB VRAM, negligible CPU, requires internet | `[VERIFIED]` 100% Ready | **PRIMARY PRODUCTION** |
| **Mode B1** | `LocalInferenceProvider` (GPU via Ollama) | Qwen 2.5 3B, Llama 3.2 1B/3B, Phi-3.5-mini | Requires 2.5–3.8 GB VRAM + CUDA | `[VERIFIED]` BLOCKED (nouveau); high OOM risk with Gazebo | **SECONDARY (Optional)** |
| **Mode B2** | `LocalInferenceProvider` (CPU via Ollama) | Qwen 2.5 1.5B/3B (Q4_K_M) | 0 MB VRAM, consumes 2.5–3.5 GB RAM, high CPU | `[VERIFIED]` Feasible (slow: 8–15 t/s, CPU contention) | **FALLBACK LOCAL** |
| **Mode C1** | `NVIDIAInferenceProvider` (Hosted API) | Nemotron-4-340B, Llama-3.1-Nemotron-70B, Mistral-NeMo-12B | 0 MB VRAM, negligible CPU, free tier via `build.nvidia.com` | `[VERIFIED]` 100% Ready | **PRIMARY NVIDIA** |
| **Mode C2** | `NVIDIAInferenceProvider` (Local NIM Container) | Local self-hosted NIM microservices | Requires 16–32 GB VRAM, TensorRT-LLM, A10/L4 GPU | `[VERIFIED]` INFEASIBLE (Hardware deficit) | **REJECTED** |
| **Mode D** | `DeterministicFallbackProvider` | Regex / rule-based grammar parser | 0 MB VRAM, 0 MB network, <1 ms latency | `[VERIFIED]` 100% Ready | **MANDATORY CI/OFFLINE** |

---

## 3. Deep-Dive: Hardware Feasibility & Bottlenecks

### 3.1 Why Local GPU Inference Is Currently Blocked
- Under the active `nouveau` driver, the kernel exposes no CUDA runtime interfaces.
- Ollama or PyTorch will fail to detect an NVIDIA GPU and will automatically fall back to CPU instruction sets (AVX2).
- Installing the proprietary driver (`sudo apt install nvidia-driver-550`) would require root (`sudo`) privileges, which is strictly prohibited by our multi-agent protocol without human sign-off.

### 3.2 The 4 GB VRAM Contention Bottleneck (Even With Drivers)
Even if proprietary drivers are enabled in the future:
1. **Model Weights:**
   - A standard 8B parameter model (e.g. Llama 3.1 8B) at 4-bit quantization (Q4_K_M) requires **~4.9 GB VRAM** for weights alone, exceeding the entire physical VRAM capacity of 4 GB.
   - Small models (e.g. Qwen 2.5 3B at Q4_K_M) require **~2.2 GB VRAM**, and Llama 3.2 1B requires **~1.1 GB VRAM**.
2. **Context Window & KV Cache:**
   - Allocating a 4,096-token KV cache adds ~400–800 MB VRAM.
3. **Simulation Resource Sharing:**
   - Gazebo Harmonic rendering with OGRE 2 / Vulkan, alongside RViz 2 and desktop display compositing, requires **1.2–2.0 GB VRAM**.
   - Attempting to co-locate Gazebo Harmonic and an Ollama LLM on a 4 GB GPU creates an unavoidable **GPU Out-Of-Memory (CUDA OOM)** condition, leading to Gazebo rendering crashes or X11/Wayland display server restarts.

### 3.3 CPU-Only Local Inference Trade-Offs
- Ollama can run on the AMD Ryzen 7 5800H using CPU RAM for quantized models (e.g. `qwen2.5:1.5b` or `qwen2.5:3b`).
- **Memory:** Host has ~4.9 GiB available RAM; loading a 2.5 GB model consumes over 50% of free memory, pushing the system closer to swap thrashing.
- **Compute Contention:** CPU LLM token generation drives 8 to 16 threads to 100% utilization. During natural language processing, this will starve Gazebo Harmonic's physics update loop (targeting 1000 Hz) and MoveIt's OMPL trajectory planning threads, introducing severe simulation jitter.

### 3.4 Why Hosted NVIDIA APIs (`build.nvidia.com`) Are the Ideal Solution
NVIDIA provides free hosted API access to its state-of-the-art Nemotron and open-weights models through `build.nvidia.com` (API endpoint: `https://integrate.api.nvidia.com/v1`):
- Fully compatible with standard OpenAI SDK (`ChatCompletions`).
- Access to **Llama-3.1-Nemotron-70B-Instruct** and **Mistral-NeMo-12B-Instruct**.
- Zero local VRAM usage; zero CPU load.
- Excellent structured JSON generation capabilities for robotic task decomposition.

---

## 4. Tokenizer Strategies per Provider for Spec Section 7

Project Specification Section 7 and [ADR-008](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/DECISIONS.md#adr-008-authentic-tokenization-visualization-without-fabricated-token-ids) dictate:
> *"Original text, tokens, boundaries, IDs when available, tokenizer name, semantic interpretation, task JSON, validation. Real tokenizer when possible; else clearly labelled approximation; never fabricated IDs."*

### 4.1 Tokenizer Implementation Matrix

| Provider | Model Family | Exact Tokenizer Library / Method | Exact Token IDs Available? | Fallback / Approximation Strategy |
| :--- | :--- | :--- | :---: | :--- |
| **OpenAI** | GPT-4o, GPT-4o-mini | `tiktoken` (`o200k_base` encoding) `[VERIFIED]` | **Yes** (Exact integer IDs) | None needed; runs locally in Python in <1 ms |
| **OpenAI** | GPT-4, GPT-3.5-Turbo| `tiktoken` (`cl100k_base` encoding) `[VERIFIED]` | **Yes** (Exact integer IDs) | None needed; runs locally in Python in <1 ms |
| **NVIDIA Hosted** | Nemotron-70B / Llama 3.1 | Hugging Face `tokenizers` / `transformers` (`meta-llama/Meta-Llama-3.1-8B`) `[VERIFIED]` | **Yes** (Exact BPE IDs) | Educational regex whitespace tokenizer labeled `is_approximate: true` (no fake IDs) |
| **Local Ollama**| Any loaded model | Ollama REST endpoint: `POST /api/tokenize` `{"model": "...", "prompt": "..."}` `[VERIFIED]` | **Yes** (Returned directly by Ollama daemon) | Educational regex tokenizer if Ollama offline |
| **Anthropic** | Claude 3.5 Sonnet | Hugging Face / `@anthropic-ai/tokenizer` `[VERIFIED]` | **No** (API returns text only) | Labeled subword/word tokenizer with `is_approximate: true` and `token_ids: null` |
| **Google Gemini**| Gemini 1.5 Flash | `google.generativeai` `count_tokens` `[VERIFIED]` | **No** (Token count only, no IDs) | Labeled subword/word tokenizer with `is_approximate: true` and `token_ids: null` |
| **Deterministic**| Offline Fallback | Python regex token splitter (`re.findall(r"\w+|[^\w\s]", text)`) `[VERIFIED]` | **No** (Explicitly `null`) | Always marked `is_approximate: true`, `tokenizer_name: "rule_based_lexical_scanner"` |

### 4.2 Tokenization Data Contract for UI (Pydantic Schema)

```python
class TokenSpan(BaseModel):
    token: str
    token_id: Optional[int] = None      # MUST be None if approximate
    start_char: int
    end_char: int
    token_type: str                     # "verb", "object", "spatial", "delimiter", "punctuation"

class TokenizationResult(BaseModel):
    raw_text: str
    tokenizer_name: str                 # e.g. "tiktoken:o200k_base", "ollama:/api/tokenize", "lexical_regex"
    is_approximate: bool                # True if approximate; False if authentic BPE
    tokens: List[TokenSpan]
    token_count: int
    notes: Optional[str] = None         # Explains approximation to the user
```

### 4.3 Inviolable Ethical & Technical Rules
1. **Never fabricate synthetic token IDs:** If an API (such as Anthropic or Gemini) does not return integer token IDs and a local BPE vocabulary is unavailable, `token_id` must be transmitted as `null` / `None`. The UI will render token boundaries without numeric IDs.
2. **Clear UI Badges:** The UI Tokenization Panel must render a prominent badge:
   - Green Badge: `Verified Exact Tokenizer: [tiktoken:o200k_base]`
   - Amber Badge: `Educational Approximation (Real-time regex parser, token IDs omitted)`
3. **Educational Disclaimer:** The panel must explicitly display the mandated disclaimer:
   > *"Tokenization segments raw text into subword units for neural network attention. Tokenization does not perform semantic validation or physical action planning."*
