# Language Model Configuration & Provider Guide

**Document ID:** MD-DOC-MODEL-001  
**Author:** Oscar - Researcher (R) (`oscar-researcher-r--mvr0bax5`)  
**Target Audience:** Operators, Developers, and Evaluators  
**System Location:** `munder_difflin/docs/model_configuration.md`  
**Reference Implementations:** `backend/app/providers/`, `backend/.env.example`, `backend/app/tokenizer.py`  
**Governance Links:** [ADR-002 (Provider Abstraction)](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/DECISIONS.md#adr-002-pluggable-languagemodelprovider-abstraction-with-deterministic-fallback), [ADR-008 (Tokenization Authenticity)](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/docs/DECISIONS.md#adr-008-authentic-tokenization-visualization-without-fabricated-token-ids)

---

## 1. Architecture Overview

Munder Difflin decouples natural language interpretation from low-level robot execution through a pluggable `LanguageModelProvider` abstraction (`backend/app/providers/base.py`). Language models propose structured tasks; they **never** control robot joints directly.

Four provider implementations are supported:

```mermaid
graph TD
    UserInstruction[Natural Language Instruction] --> Chain[ProviderChain (chain.py)]
    Chain --> StatusCheck{Check Configured & Available}
    
    StatusCheck -->|Configured & Ready| Cloud[CloudAPIProvider<br/>Anthropic Messages API]
    StatusCheck -->|Configured & Ready| NVIDIA[NVIDIAInferenceProvider<br/>Hosted OpenAI-Compatible]
    StatusCheck -->|Daemon Reachable| Local[LocalInferenceProvider<br/>Ollama REST API]
    
    Cloud -->|HTTP 4xx/5xx or Malformed| RetryFail[Validate & Retry x2]
    NVIDIA -->|HTTP 4xx/5xx or Malformed| RetryFail
    Local -->|HTTP 4xx/5xx or Malformed| RetryFail
    
    RetryFail -->|Failed or Skipped| Fallback[DeterministicFallbackProvider<br/>Rule-based Lexical Parser]
    StatusCheck -->|All Skipped| Fallback
    
    Cloud -->|Valid TaskPlan JSON| Validator[World & Safety Validator]
    NVIDIA -->|Valid TaskPlan JSON| Validator
    Local -->|Valid TaskPlan JSON| Validator
    Fallback -->|Valid TaskPlan JSON| Validator
```

---

## 2. Hardware Reality & Host Feasibility

Before configuring providers, review the audited host hardware profile:

| Subsystem | Host Specification | Status & Impact on AI Inference |
| :--- | :--- | :--- |
| **GPU** | NVIDIA GeForce RTX 3050 Mobile (GA107M) | **4 GB GDDR6 VRAM** (verified via PCI BAR address range `4G`). |
| **Driver** | Open-source `nouveau` | **Proprietary NVIDIA driver and CUDA are NOT installed.** `nvidia-smi` is not present. |
| **System RAM** | 14.0 GiB total (~15 GB) | **~4.9 GiB available at baseline**; 1.7 GiB swap active. |
| **CPU** | AMD Ryzen 7 5800H | 8 cores, 16 threads (3.2 GHz base, 4.4 GHz boost). |

### Practical Operational Rules:
1. **Primary Production Paths:** Use **Cloud APIs** (Anthropic) or **Hosted NVIDIA APIs** (`build.nvidia.com`). They consume 0 MB host VRAM and negligible CPU, preserving all system resources for Gazebo Harmonic and MoveIt 2.
2. **Local GPU Inference is Blocked:** Under `nouveau`, CUDA acceleration is disabled. Furthermore, even with proprietary drivers, 4 GB VRAM cannot safely co-host an LLM and Gazebo Harmonic's rendering engine without triggering CUDA Out-Of-Memory (OOM) crashes.
3. **Local CPU Inference (Ollama):** Permitted for small models ($\le 3\text{B}$ parameters). Note that CPU inference spikes multi-core CPU usage, which risks starving Gazebo's real-time physics thread (1000 Hz target).
4. **Offline / CI Testing:** Use the **Deterministic Fallback Provider** (0 memory overhead, <1 ms latency, 100% deterministic).

---

## 3. Provider Configuration Guide

All providers read credentials and model selections strictly from environment variables or a local `.env` file in `munder_difflin/backend/.env`. **Never hardcode or commit API keys to version control.**

### 3.1 Mode A: Cloud API Provider (`CloudAPIProvider`)

- **Implementation:** [`backend/app/providers/http_providers.py`](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/backend/app/providers/http_providers.py#L44)
- **Protocol:** Anthropic Messages API (`/v1/messages`)
- **Key Features:** High semantic reasoning, native structured JSON output adherence, low latency.

#### Environment Variables (`backend/.env`):
```bash
# Required to enable Cloud provider
ANTHROPIC_API_KEY=sk-ant-api03-...

# Model selection (Default: claude-sonnet-5-5)
MD_CLOUD_MODEL=claude-sonnet-5-5

# Optional custom proxy or mock endpoint (Default: https://api.anthropic.com)
MD_CLOUD_BASE_URL=https://api.anthropic.com
```

The default model `claude-sonnet-5-5` belongs to the current Claude 5 model family (`claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`). Operators can override `MD_CLOUD_MODEL` to target specific model variants as desired.

---

### 3.2 Mode B: Hosted NVIDIA Inference Provider (`NVIDIAInferenceProvider`)

- **Implementation:** [`backend/app/providers/http_providers.py`](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/backend/app/providers/http_providers.py#L121)
- **Protocol:** OpenAI-compatible Chat Completions endpoint (`/chat/completions`)
- **Endpoint:** `https://integrate.api.nvidia.com/v1` (documented NVIDIA hosted NIM entrypoint; *not tested with a live key*)
- **Key Features:** Hosted inference via [build.nvidia.com](https://build.nvidia.com), access to Nemotron and open models, zero local VRAM consumption.

#### Environment Variables (`backend/.env`):
```bash
# Required to enable NVIDIA provider (obtain key from build.nvidia.com)
NVIDIA_API_KEY=nvapi-...

# Base URL (Default: https://integrate.api.nvidia.com/v1)
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1

# Target Model ID (Default: meta/llama-3.1-8b-instruct)
NVIDIA_MODEL=meta/llama-3.1-8b-instruct
```

#### Documented Hosted Model Identifiers in NVIDIA Catalog:
- `meta/llama-3.1-8b-instruct` *(Default fast model in backend configuration)*
- `nvidia/llama-3.1-nemotron-70b-instruct` *(Flagship Nemotron reasoning model; option for high complexity)*
- `mistralai/mistral-nemo-12b-instruct`
*(Note: Live endpoint responsiveness with user keys depends on active NVIDIA service tiers and has not been tested with a live key in this environment).*

---

### 3.3 Mode C: Local Inference Provider (`LocalInferenceProvider`)

- **Implementation:** [`backend/app/providers/http_providers.py`](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/backend/app/providers/http_providers.py#L80)
- **Protocol:** Ollama REST API (`/api/chat` with `"format": "json"`)
- **Verified Host State:** `ollama version is 0.5.7` is installed and running (`ollama serve` active).

#### Environment Variables (`backend/.env`):
```bash
# Ollama service address (Default: http://localhost:11434)
OLLAMA_HOST=http://localhost:11434

# Model name tag in Ollama (Default: llama3.2)
MD_LOCAL_MODEL=llama3.2
```

#### Observed Host State & Memory Considerations:
Inspection of the host system (`ollama list`) verified the following installed models:
```
NAME              ID              SIZE      MODIFIED
qwen:14b          80362ced6553    8.2 GB    20 months ago
deepseek-r1:7b    0a8c26691023    4.7 GB    20 months ago
```
- The default model `llama3.2` is currently **not pulled** in the local Ollama daemon (`status().available` will report `false` until pulled).
- Available host RAM is **~4.9 GiB free** with no CUDA acceleration. The existing local models (`qwen:14b` at 8.2 GB and `deepseek-r1:7b` at 4.7 GB) exceed or saturate available free memory, which risks heavy swap thrashing if loaded into system RAM.
- **Operator Suggestion:** If testing local CPU inference, operators may consider pulling smaller models (such as `qwen2.5:1.5b` or `llama3.2:1b`) to fit comfortably within free RAM and mitigate CPU contention against Gazebo Harmonic.

---

### 3.4 Mode D: Deterministic Fallback Provider (`DeterministicFallbackProvider`)

- **Implementation:** [`backend/app/providers/fallback.py`](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/backend/app/providers/fallback.py)
- **Protocol:** Local in-process regex/lexical parser.
- **Key Features:** Requires **no API keys, no network connection, and no models**. Guarantees 100% passing tests for standard benchmark commands:
  - `"pick up the red cube and place it in the storage box"`
  - `"move blue cube to the right side of the table"`
  - `"pick red cube and place in box without touching blue cube"`
  - Ambiguous requests (e.g. `"move the box to the left"`) correctly generate `ClarificationRequest`.

---

## 4. Provider Selection & Fallback Mechanics (`providers/chain.py`)

The pipeline utilizes `ProviderChain` ([`backend/app/providers/chain.py`](file:///home/sudharshan/Documents/Robotic%20Operation%20with%20Prompt%20Engineering/munder_difflin/backend/app/providers/chain.py)) to evaluate commands reliably:

1. **Sequential Discovery:** The chain iterates over registered providers in priority order (e.g. Cloud $\rightarrow$ NVIDIA $\rightarrow$ Local).
2. **Health & Availability Gate:** Before invoking inference, the chain calls `provider.status()`. If credentials are unset or the service is unreachable, it logs `outcome="skipped"` and proceeds immediately without timing out.
3. **Validate-and-Retry Loop:** When an available provider responds with text that fails Pydantic schema validation, `LLMProvider.parse()` automatically feeds the exact validation error back to the model up to `max_retries=2` times before declaring failure.
4. **Deterministic Fallback Interlock:** If all external providers fail or are skipped, the chain falls back to `DeterministicFallbackProvider`, setting `used_fallback=True`. The user instruction is never dropped silently, and the UI displays each attempt's outcome.

---

## 5. Tokenization Visualization & Authenticity (ADR-008)

Project Specification Section 7 requires an authentic tokenization inspection panel without deceptive synthetic token IDs.

### Implementation in `backend/app/tokenizer.py`:

```python
class Tokenizer(Protocol):
    name: str
    def tokenize(self, text: str) -> TokenizationResult: ...
```

1. **Exact BPE Tokenization (`TiktokenTokenizer`):**
   - Uses `tiktoken` library (encoding `cl100k_base` or `o200k_base`).
   - Generates exact byte-pair token strings, character offset boundaries, and integer `token_id`s.
   - Sets `is_live_model_tokenization=True`.
2. **Authentic Approximation (`ApproximateTokenizer`):**
   - Active when offline or using models without open tokenizer weights.
   - Splits text using word/punctuation regex (`r"[A-Za-z]+|\d+|[^\sA-Za-z\d]"`).
   - Sets `is_approximate=True` and leaves `token_id=None`. **Never generates fake integer IDs.**
3. **Mandatory Educational Disclaimer:**
   The panel displays the verified project notice:
   > *"Tokenization segments raw text into subword units for neural network attention. Tokenization does not perform semantic validation or physical action planning."*

---

## 6. Verified Host Observations & Configuration Notes

Summary of observed facts vs operator suggestions:

1. **Cloud Model Configuration:**
   - `claude-sonnet-5-5` is configured as the active default model in `backend/app/providers/http_providers.py` and `backend/.env.example`.
2. **NVIDIA Inference Endpoint:**
   - Base URL `https://integrate.api.nvidia.com/v1` is documented by NVIDIA developer guides for hosted inference.
   - Default model in code is `meta/llama-3.1-8b-instruct`. Live key authentication and live model latency have not been tested with a live key.
3. **Ollama Local Status:**
   - Verified active: `ollama version is 0.5.7`.
   - Verified models present: `qwen:14b` (8.2 GB) and `deepseek-r1:7b` (4.7 GB). Default `llama3.2` is not pulled.
   - System memory caveat: Host has ~4.9 GiB free RAM. The installed models risk heavy swap thrashing on CPU. Pulling smaller models ($\le 3\text{B}$) is suggested for operators testing local CPU mode.
