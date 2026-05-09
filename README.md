# SplatChain

**Tamper-proof provenance for any 3D asset — proves a capture is real, not AI-generated, and hasn't been modified since.**

SplatChain creates an immutable chain of custody from raw sensor capture through trained model — verifiable by any viewer in under 2 seconds, at under a cent.

```
[CAPTURE] ──attests──► [TRAINING] ──receipts──► [ON-CHAIN] ──registers──► [VERIFIED]
  device                 pipeline                  registry                  badge
  signing                signing                 smart contract
```

---

## The Problem

AI can now generate photorealistic 3D Gaussian Splats indistinguishable from real-world captures. There is no standard to verify that a splat originated from actual sensor data. Anyone can steal a splat, re-process it, and claim it as their own.

SplatChain solves this with a two-hash, three-stage provenance system anchored on Base L2.

---

## How It Works

### 1. Capture Attestation
Before training, the capture device hashes all raw input files (photos, depth maps, GPS, IMU) into a single `input_hash`. A deterministic coded frame hash — ~20 frames selected by seeded RNG — creates a fingerprint nearly impossible to fake without the original data. The device signs everything with its Ed25519 private key.

Output: `capture_attestation.json`

### 2. Training Receipt
After training, the pipeline hashes the output `.ply`/`.splat` file into `model_hash` and binds it to `input_hash` from step 1. This pre-image binding proves *this model came from that input*. The pipeline signs with its own Ed25519 key.

Output: `training_receipt.json`

### 3. On-Chain Registry
`model_hash` + `input_hash` are registered on Base L2 via `SplatRegistry.sol`. One input can only produce one registered model — duplicates are rejected at the contract level.

**Trust tiers:**
| Tier | Who | How |
|------|-----|-----|
| 1 | Anyone | Self-attested via `attest()` |
| 2 | Approved pipelines | Verified by owner/DAO via `approveAttester()` |
| 3 | Hardware-attested | TEE/SGX pipeline (roadmap) |

---

## Verification

```python
from splatchain import verify

result = verify("my_scene.ply", sidecar="my_scene.verify.json")
print(result.badge, result.status)
# ✅ verified
```

| Status | Badge | Meaning |
|--------|-------|---------|
| `verified` | ✅ | On-chain + valid signatures |
| `attested_unverified` | ⚠️ | On-chain, no sidecar to check sigs |
| `revoked` | 🚫 | Creator or owner revoked it |
| `sig_invalid` | ⚠️ | Signature mismatch — tampered |
| `unverified` | ⚠️ | Not found on registry |

---

## Live Test Results (Sepolia)

| # | Test | Result |
|---|------|--------|
| 1 | Attest splat (iphone_lidar, ply) | ✅ 253k gas |
| 2 | Read attestation back | ✅ All fields match |
| 3 | isVerified check | ✅ True |
| 4 | Trust tier | ✅ Tier 2 (deployer is approved attester) |
| 5 | Input→model lookup | ✅ Found |
| 6 | Second attestation (dslr_photogrammetry, splat) | ✅ Tier 2 |
| 7 | Duplicate attestation rejection | ✅ Reverted "Already attested" |
| 8 | Revoke attestation | ✅ isVerified=false, tier=0 |
| 9 | Count: 2 total, 2 by deployer | ✅ |

9/9 on-chain tests passing. 11/11 integration tests passing.

---

## Installation

**Python SDK + CLI:**
```bash
pip install splatchain
```

**Solidity (Hardhat):**
```bash
cd solidity
npm install
```

**Requirements:** Python ≥ 3.10, Node.js for contract work.

---

## CLI

```bash
# Attest a capture
splatchain attest --files ./photos/ --device-key device.key

# Create training receipt
splatchain receipt --input-hash <hash> --model my_scene.ply --pipeline-key pipeline.key

# Verify a splat
splatchain check my_scene.ply

# Register on-chain
splatchain register my_scene.ply --rpc-url https://sepolia.base.org
```

---

## Smart Contract

`SplatRegistry.sol` — deployed on Ethereum Sepolia (Base mainnet when ready via `--network base`).

**Key functions:**
```solidity
attest(inputHash, modelHash, captureMethod, modelFormat)  // ~253k gas
revoke(modelHash, reason)
isVerified(modelHash) → bool
getTier(modelHash) → uint8
getModelByInput(inputHash) → bytes32
```

Gas cost on Base mainnet: fractions of a cent per attestation.

---

## PlayCanvas Plugin

`playcanvas/splat-verify-plugin.js` — drop-in viewer verification:
- Loads `.verify.json` sidecar alongside `.ply`/`.splat`
- Verifies Ed25519 signatures in-browser via WebCrypto
- Queries on-chain registry via ethers.js
- Renders ✅/⚠️/🚫 badge overlay with provenance panel

---

## Project Structure

```
splatchain/
├── splatchain/          # Python SDK
│   ├── capture.py       # Capture attestation
│   ├── training.py      # Training receipt
│   ├── verify.py        # Verification logic
│   ├── registry.py      # On-chain registry client
│   ├── crypto.py        # Ed25519 + SHA-256 utils
│   └── cli.py           # CLI entrypoint
├── solidity/            # Smart contract
│   ├── contracts/
│   │   └── SplatRegistry.sol
│   ├── scripts/         # Deploy scripts
│   └── test/            # Hardhat tests
├── playcanvas/          # Viewer plugin
├── tests/
│   └── test_integration.py
└── SPEC.md              # Full technical spec
```

---

## Threat Model

| Attack | Mitigation |
|--------|-----------|
| AI-generated splat with fake attestation | Requires valid device Ed25519 key |
| Stolen capture + AI-generated model | `input_hash` won't bind to model |
| Modify splat post-attestation | `model_hash` changes, on-chain record won't match |
| Replay old attestation | `model_hash` is file-derived, can't reuse |
| Stolen device key | DAO can revoke. Tier system limits blast radius |
| Registry offline | Viewers show "Unverified (offline)", cache last-known state |

---

## Roadmap

- [x] Python SDK (capture, training, verify)
- [x] Solidity registry — Sepolia testnet
- [x] CLI tool
- [x] PlayCanvas verification plugin
- [x] 9/9 on-chain tests, 11/11 integration tests
- [ ] Base mainnet deployment
- [ ] Device key management + rotation
- [ ] Mobile capture SDK (iOS/Android)
- [ ] DAO governance for Tier 2 attesters
- [ ] TEE/SGX hardware attestation (Tier 3)
- [ ] Ponder indexer for fast off-chain lookups

---

## License

MIT
