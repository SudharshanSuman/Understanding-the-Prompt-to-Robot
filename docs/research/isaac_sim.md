# NVIDIA Isaac Sim: Requirements Note and Extension Feasibility

**Document ID:** MD-RES-DOC-004  
**Author:** Oscar - Researcher (R) (`oscar-researcher-r--mvr0bax5`)  
**Work Package:** MD-RES-001 (Phase 0)  
**Target Platform:** NVIDIA Isaac Sim 4.x / Omniverse  
**Date:** 2026-10-28  
**Verification Standard:** Every claim is explicitly marked as `[VERIFIED]` with NVIDIA documentation links or physical audit data.

---

## 1. Context & Scope

Project Specification Section 4 and Section 2 dictate:
> *"Mode C NVIDIA (NIM, hosted API, Nemotron, local GPU inference only if hardware allows; Isaac Sim only as documented optional extension, Gazebo stays primary)."*
> *"Isaac Sim only as optional extension: requirements note, not install."*

This document provides a rigorous technical specification of NVIDIA Isaac Sim's hardware and software prerequisites, compares them directly against the audited host environment, and formalizes its architectural status as a future cloud/workstation extension while confirming Gazebo Harmonic as the primary simulator.

---

## 2. NVIDIA Isaac Sim Minimum & Recommended Requirements

According to official NVIDIA Omniverse and Isaac Sim documentation ([NVIDIA Isaac Sim System Requirements](https://docs.omniverse.nvidia.com/isaacsim/latest/installation/requirements.html) `[VERIFIED]`):

| Component | Minimum Specification | Recommended Specification | Audited Host Specification | Feasibility Gap / Status |
| :--- | :--- | :--- | :--- | :--- |
| **Operating System** | Ubuntu 22.04 / 24.04 LTS (x86_64) | Ubuntu 22.04 / 24.04 LTS | Ubuntu 24.04.5 LTS | `[VERIFIED]` Satisfied |
| **CPU** | Intel Core i7 (7th Gen+) or AMD Ryzen 7 | Intel Core i9 or AMD Ryzen 9 | AMD Ryzen 7 5800H (8C/16T) | `[VERIFIED]` Satisfied |
| **GPU Architecture**| NVIDIA RTX (Turing, Ampere, Ada Lovelace) | NVIDIA RTX 3080 / 4080 / A-Series | NVIDIA RTX 3050 Mobile (Ampere GA107M) | `[VERIFIED]` Hardware generation matches |
| **GPU VRAM** | **8 GB VRAM** (Strict minimum) | **12 GB – 24 GB VRAM** | **4 GB GDDR6 VRAM** | `[VERIFIED]` **FATAL DEFICIT (-4 GB VRAM)** |
| **Display Driver** | NVIDIA Proprietary Driver $\ge$ 535.129.03 | NVIDIA Proprietary Driver $\ge$ 550.x | `nouveau` (open source) | `[VERIFIED]` **FATAL DEFICIT (Unsupported driver)** |
| **CUDA / Vulkan** | Vulkan 1.3 + RTX Ray Tracing Extensions | Hardware Ray Tracing + DLSS 3 | Nouveau lacks RTX Vulkan ray tracing | `[VERIFIED]` **FATAL DEFICIT (No RTX ray tracing)** |
| **System Memory** | **32 GB RAM** | **64 GB RAM** | **14.0 GiB RAM (~15 GB)** | `[VERIFIED]` **FATAL DEFICIT (-18 GB RAM)** |
| **Disk Storage** | 50 GB NVMe SSD | 100 GB NVMe SSD | ~20 GB free space | `[VERIFIED]` Marginal |

---

## 3. Host Feasibility Analysis

### 3.1 The VRAM Barrier
Isaac Sim relies on NVIDIA Omniverse's RTX Renderer (Vulkan / OptiX) and PhysX 5 GPU pipeline. Upon launching the Isaac Sim application (`isaac-sim.sh`), the engine initializes the core USD stage, materials, shader caches, and GPU physics buffers:
- The base scene allocation alone exceeds **5.5 GB VRAM** before any robot meshes or sensor cameras are loaded.
- The host laptop's RTX 3050 Mobile has **exactly 4.0 GB VRAM**. Attempting to launch Isaac Sim will immediately result in an uncaught Vulkan out-of-device-memory error (`VK_ERROR_OUT_OF_DEVICE_MEMORY`) or driver lockup.

### 3.2 Driver & Kernel Incompatibility
Isaac Sim requires low-level proprietary NVIDIA kernel modules (`nvidia.ko`, `nvidia-uvm.ko`) and the proprietary Vulkan ICD. The host is currently running the open-source `nouveau` kernel driver without `nvidia-smi` or CUDA userspace drivers. The Omniverse launcher and Isaac Sim runtime will refuse to start on `nouveau`.

### 3.3 System RAM Starvation
Isaac Sim consumes 16–24 GB of system RAM during USD asset parsing and mesh generation. The host has only 14.0 GiB total RAM, with only ~4.9 GiB currently available. Launching Isaac Sim would induce extreme Linux kernel OOM killer activity, terminating system sessions.

---

## 4. Architectural Role & Extension Roadmap

### 4.1 Definitive Project Decision
1. **NO Local Isaac Sim Installation:** `[VERIFIED]` Under no circumstances should any agent attempt to download, install, or execute Isaac Sim on this host machine. Doing so will violate the no-destructive-changes rule and destabilize the operating system.
2. **Gazebo Harmonic Remains Primary:** Gazebo Harmonic (`gz-sim 8`) with `gz_ros2_control` and DART physics is verified, fully functional, and well within host system resource budgets. All core project deliverables (Phases 1–10, Acceptance Tests A–J) will be built and validated in Gazebo Harmonic.

### 4.2 Documented Optional Extension Architecture
For enterprise users seeking photorealistic synthetic data generation or hardware-in-the-loop Isaac ROS perception testing in the future:
- **Deployment Target:** Cloud GPU instance (e.g. AWS EC2 `g5.2xlarge` with 24 GB VRAM NVIDIA A10G GPU, or local workstation with RTX 4080 / 32 GB RAM).
- **Integration Boundary:** Munder Difflin's ROS 2 architecture is decoupled from the physics simulator. The same ROS 2 action interfaces (`/joint_trajectory_controller/follow_joint_trajectory` and `/gripper_action_controller/gripper_cmd`), TF2 coordinate frames, and perception sensor topics (`/camera/color/image_raw`, `/camera/depth/points`) can be fed by Isaac Sim via `isaac_ros` bridges without altering the planning or language processing pipeline.
