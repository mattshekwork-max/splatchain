# SplatChain — Blockchain-Verified Gaussian Splat Provenance

## Problem

AI can generate photorealistic 3D Gaussian Splats indistinguishable from real-world captures. No standard exists to verify that a splat originated from actual sensor data vs. AI generation.

## Scope

A verification system that creates an immutable provenance chain from raw capture through trained model, verifiable by any viewer (PlayCanvas, WebGL, native).

---

## Architecture Overview

```
CAPTURE DEVICE          TRAINING PIPELINE           CHAIN              VIEWER
─────────────          ─────────────────           ─────              ──────
Photos + LiDAR    ──►  Colmap/optics       ──►    SplatRegistry   ──►  Verify
      │                 │                       (on-chain)            │
      ▼                 ▼                             ▼               ▼
  device_hash      train_hash                   attestation       render with
  + GPS/timestamp   + model_hash                 (minted)         badge/lock
      │                 │                             │
      └───── pre-image ─┘                             │
           proof                                         receipt
```

Four phases. Two hashes. One on-chain record per splat.

---

## 1. Capture Attestation

**Goal:** Prove raw input data existed before the model was trained.

### Device-Side (mobile app / desktop CLI)

On capture completion:

1. **Hash all input files** — SHA-256 of concatenated input data (photos + depth maps + GPS + IMU + timestamps). Call this `input_hash`.
2. **Collect metadata JSON:**
   ```json
   {
     "device_id": "sha256(serial+model)",
     "gps": { "lat": 34.0522, "lon": -118.2437, "alt": 71, "accuracy_m": 3.2 },
     "timestamp": "2026-05-08T07:44:10Z",
     "capture_method": "iphone_lidar|dslr_photogrammetry|drone|terrestrial_scanner",
     "photo_count": 127,
     "sensor_types": ["rgb", "lidar", "imu"],
     "duration_s": 342,
     "input_hash": "sha256(...)..."
   }
   ```
3. **Sign with device key** — Each device holds an Ed25519 keypair. Signature over `input_hash + metadata_hash`. This is the `capture_attestation`.
4. **Output:** `capture_attestation.json` — bundled alongside raw data.

### Why Ed25519, not Ethereum tx
Device signing happens offline (captures happen in the field). Ed25519 is fast, small (64-byte sig), and doesn't require gas or network. We convert to on-chain format later.

---

## 2. Training Provenance

**Goal:** Prove the trained splat was derived from the attested input data.

### Training Pipeline

After training completes:

1. **Hash the output splat** — SHA-256 of the final `.ply` or `.splat` file. Call this `model_hash`.
2. **Create training receipt:**
   ```json
   {
     "input_hash": "<from capture attestation>",
     "model_hash": "sha256(...)...",
     "model_format": "ply|splat|ksplat",
     "model_size_bytes": 524288000,
     "gaussian_count": 402873,
     "training_config_hash": "sha256 of config YAML",
     "training_runtime_s": 1847,
     "psnr": 31.2,
     "ssim": 0.94,
     "pipeline": "gaussian-splatting|nerfstudio|postshot",
     "pipeline_version": "0.1.0"
   }
   ```
3. **Sign with pipeline key** — Separate Ed25519 key per pipeline/build. Proves which training system generated the model.
4. **Output:** `training_receipt.json` — bundled alongside the splat file.

### Pre-Image Binding

The critical link: `input_hash` appears in BOTH the capture attestation AND the training receipt. This creates a pre-image proof — you can't produce a valid training receipt without having the input data that hashes to `input_hash`.

---

## 3. On-Chain Registry

**Goal:** Immutable, publicly verifiable record.

### Smart Contract (Solidity, deploy on Base/L2)

```solidity
contract SplatRegistry {
    struct Attestation {
        address creator;
        bytes32 inputHash;
        bytes32 modelHash;
        string  captureMethod;
        string  modelFormat;
        uint256 timestamp;
        bool    revoked;
    }
    
    mapping(bytes32 => Attestation) public splats; // modelHash => Attestation
    mapping(address => bool) public attesters;       // approved attesters
    
    event SplatAttested(bytes32 indexed modelHash, bytes32 inputHash, address creator);
    event SplatRevoked(bytes32 indexed modelHash, string reason);
    
    function attest(bytes32 inputHash, bytes32 modelHash, string calldata captureMethod, string calldata modelFormat) external {
        require(!splatVerify(msg.sender, modelHash), "already attested");
        splats[modelHash] = Attestation(msg.sender, inputHash, modelHash, captureMethod, modelFormat, block.timestamp, false);
        emit SplatAttested(modelHash, inputHash, msg.sender);
    }
    
    function revoke(bytes32 modelHash, string calldata reason) external onlyAttester {
        splats[modelHash].revoked = true;
        emit SplatRevoked(modelHash, reason);
    }
}
```

### Attestation Flow

1. User uploads splat to hosting (IPFS/Arweave/S3)
2. Client calls `attest()` on the registry contract
3. Gas: ~50k gas on Base L2 ≈ $0.01. Acceptable.
4. Optional: bundle capture_attestation + training_receipt signatures as calldata or store off-chain (IPFS) with CID in event logs

### Attester Model

- **Self-attestation** — Anyone can attest their own splats. Trust = reputation.
- **Verified attesters** — DAO or multisig can approve attesters who run trusted pipelines. Their splats get a higher trust tier.
- **Three tiers:**
  - Tier 1: Self-attested (any wallet) — baseline provenance
  - Tier 2: Verified attester (approved pipeline) — strong provenance
  - Tier 3: Hardware-attested (TEE/SGX pipeline) — strongest provenance

---

## 4. Viewer Verification

**Goal:** PlayCanvas viewer checks provenance before/during rendering.

### Verification Flow

```
splat.sply file loads
       │
       ▼
Extract model_hash (SHA-256 of file)
       │
       ▼
Query SplatRegistry.getModelHash(model_hash)  ──►  on-chain lookup
       │                                            │
       ├─ NOT FOUND ──►  Render with ⚠️ "Unverified" badge
       │
       ├─ FOUND, revoked ──►  Render with 🚫 "Revoked" overlay
       │
       └─ FOUND, valid ──►  Verify signatures:
                             - capture_attestation.sig valid for input_hash?
                             - training_receipt.sig valid for model_hash?
                             - input_hash matches between both?
                                    │
                                    ├─ YES ──►  Render with ✅ "Verified" badge
                                    │             + show provenance panel
                                    │             (GPS, timestamp, device, method)
                                    │
                                    └─ NO ──►  Render with ⚠️ "Attested but sigs invalid"
```

### PlayCanvas Integration

- **Custom shader pass** — overlay badge (✅/⚠️/🚫) in corner of XR viewport
- **Provenance panel** — click badge to see: capture method, GPS, timestamp, attester address, on-chain tx
- **Hot load** — verification happens in parallel with splat download. No render delay.
- **Offline fallback** — if chain unavailable, show "Unverified (offline)" badge. Cache last-known state.

### Badge Design

```
┌─────────────────────────┐
│  ✅ VERIFIED CAPTURE     │
│  iPhone 15 Pro · LiDAR  │
│  34.05°N, 118.24°W      │
│  2026-05-08 · 402K pts  │
│  Attester: 0x7a3f...    │
│  [View on-chain ↗]      │
└─────────────────────────┘
```

---

## File Format Extension

Standard .ply/.splat files need a way to carry provenance metadata without breaking existing viewers.

### Option A: Sidecar file (recommended)

`splat.ply` + `splat.verify.json` sidecar:

```json
{
  "version": 1,
  "model_hash": "sha256:abc123...",
  "input_hash": "sha256:def456...",
  "capture_attestation": { ... },
  "training_receipt": { ... },
  "chain": {
    "registry_address": "0x...",
    "chain_id": 8453,
    "tx_hash": "0x...",
    "block_number": 12345678,
    "attester_tier": 2
  }
}
```

Pros: Backward compatible. Existing viewers ignore the sidecar. Verifying viewers read it.

### Option B: Custom header in .splat format (future)

Append a provenance section to the .splat binary format with a magic marker. PlayCanvas can parse it; other viewers skip it.

---

## Threat Model

| Attack | Mitigation |
|--------|-----------|
| AI-generated splat with fake attestation | Need valid device signature from attested device key. Attacker doesn't have the key. |
| Real capture attestation + AI-generated splat | Input_hash won't bind to model. Training receipt signature must match pipeline key. |
| Stolen device key | Attester DAO can revoke compromised keys. Tier system limits blast radius. |
| Replay old attestation on different splat | model_hash is computed from splat file. Can't reuse old hashes. |
| Modify splat post-attestation | model_hash changes. On-chain record doesn't match. Fails verification. |
| Modify raw input data | input_hash changes. Training receipt no longer binds. |
| Sybil attester (self-attest everything) | Tier system. Self-attested = Tier 1, limited trust. Verified attesters = Tier 2. |
| Chain unavailable | Viewers show "Unverified (offline)". Cache last-known state per model_hash. |

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Chain | Base (L2) | Low gas, Ethereum security, EVM compatible |
| Smart contract | Solidity | Standard, auditable, well-tooled |
| Signing | Ed25519 | Fast, small, offline-friendly |
| Hashing | SHA-256 (output) / BLAKE3 (input, optional) | Standard; BLAKE3 faster for large point clouds |
| Hosting | IPFS or Arweave | Content-addressed, immutable |
| Viewer | PlayCanvas + GSplat extension | Best web SPLAT renderer, extensible |
| SDK | TypeScript + Python | TS for web/PlayCanvas, Python for capture pipeline |
| Indexer | Ponder or Viem | On-chain event indexing for fast lookups |

---

## MVP Scope (v0.1)

1. **Python capture SDK** — hash input data, sign with device key, output `capture_attestation.json`
2. **Solidity registry** — deploy to Base testnet, `attest()` + `revoke()` + `getModelHash()`
3. **Python training receipt** — post-training hook, output `training_receipt.json`
4. **PlayCanvas verification viewer** — load splat, compute model_hash, check registry, show badge
5. **CLI tool** — `splatchain attest <files>` / `splatchain check <splat.ply>`

Out of scope for v0.1: TEE attestation, DAO governance, mobile app, custom binary format.

---

## Open Questions

1. **Splat compression** — If the hosting platform compresses/transcodes the .ply, model_hash breaks. Solutions: hash before compression, or hash uncompressed canonical form. Need a standard.
2. **Partial captures** — What if you add/remove input photos and retrain? New attestation needed, or allow amendments?
3. **Model versioning** — Same input, retrained with better params = new model_hash. Link to parent attestation?
4. **Privacy** — GPS coordinates in on-chain data. Option to hash/obfuscate location while still proving provenance?
5. **Viewer enforcement** — Should viewers REFUSE to render unverified splats, or just show a badge? Probably badge only — forcing would fragment the ecosystem.
6. **AI-assisted cleanup** — Many real captures use AI for noise removal or hole-filling during training. Where's the line? Need a `post_processing` field in training receipt.

---

## Names (pick one)

- SplatChain
- SplatSeal  
- Provenance3D
- SplaChain
- TrustSplat

---

## Timeline (v0.1 MVP)

| Week | Deliverable |
|------|-------------|
| 1 | Python SDK (capture attestation + training receipt) |
| 1 | Solidity contract + Base testnet deploy |
| 2 | PlayCanvas verification plugin |
| 2 | CLI tool |
| 3 | Test with real Gaussian Splatting pipeline |
| 3 | Documentation + demo video |