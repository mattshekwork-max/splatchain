# SplatChain PlayCanvas Plugin

Blockchain-verified Gaussian Splat provenance for PlayCanvas viewers.

## What It Does

When a `.splat` or `.ply` file loads in a PlayCanvas scene, this plugin:

1. **Computes the model hash** (SHA-256 of the file) using Web Crypto — no server needed
2. **Queries SplatRegistry** on-chain for that hash (via ethers.js on Base/mainnet)
3. **Verifies Ed25519 signatures** from the `.verify.json` sidecar (capture attestation + training receipt)
4. **Renders a badge overlay** with verification status (verified, attested, revoked, unverified)
5. **Shows a provenance panel** on click — capture method, GPS coordinates, timestamp, attester address, on-chain link

## Install

```bash
npm install @splatverify/playcanvas
# Optional but recommended for on-chain verification:
npm install ethers @noble/ed25519
```

## Quick Start

```js
import { SplatChainPlugin } from '@splatchain/playcanvas';

const plugin = new SplatChainPlugin(app, {
  registryAddress: '0x...',   // Deployed SplatRegistry contract
  chainId: 8453,              // Base mainnet (default)
  rpcUrl: 'https://mainnet.base.org',
  showPanel: true,            // Show provenance detail panel (default: true)
});

// After loading your splat:
const result = await plugin.attach(splatEntity, {
  splatData: arrayBuffer,     // Raw .ply/.splat bytes
  splatUrl: 'https://...',    // URL (for sidecar auto-detection)
});

console.log(result.status);   // 'verified' | 'attested_unverified' | 'revoked' | etc.
console.log(result.tier);     // 1 (self-attested) | 2 (verified attester) | 3 (TEE)
console.log(result.badge);    // '✅' | '⚠️' | '🚫' | etc.
```

## Standalone Hash (No PlayCanvas)

```js
import { computeModelHash } from '@splatverify/playcanvas/hash';

const hash = await computeModelHash(fileBuffer);
// → 'sha256:abc123...'
```

## Sidecar Format

Place a `scene.splat.verify.json` next to your `scene.splat` file:

```json
{
  "version": 1,
  "model_hash": "sha256:abc123...",
  "input_hash": "sha256:def456...",
  "capture_attestation": {
    "device_id": "sha256(serial+model)",
    "gps": { "lat": 34.0522, "lon": -118.2437, "alt": 71 },
    "timestamp": "2026-05-08T07:44:10Z",
    "capture_method": "iphone_lidar",
    "input_hash": "sha256:def456...",
    "signature": "..."
  },
  "training_receipt": {
    "input_hash": "sha256:def456...",
    "model_hash": "sha256:abc123...",
    "model_format": "ply",
    "gaussian_count": 402873,
    "pipeline": "gaussian-splatting",
    "pipeline_public_key": "...",
    "signature": "..."
  },
  "chain": {
    "registry_address": "0x...",
    "chain_id": 8453,
    "tx_hash": "0x...",
    "attester_tier": 2
  }
}
```

## Badge States

| Status | Badge | Meaning |
|--------|-------|---------|
| `verified` | ✅ | Full provenance: on-chain + valid signatures |
| `attested_unverified` | ⚠️ | On-chain attestation but sigs can't be verified |
| `revoked` | 🚫 | Attestation revoked on-chain |
| `unverified` | ⚠️ | No provenance data found |
| `offline` | 📡 | Registry unreachable, cached data only |
| `sig_invalid` | ⚠️ | Signature doesn't match expected hash |

## Architecture

```
splat file loads
       │
       ▼
Compute model_hash (SHA-256 via Web Crypto)
       │
       ▼
Fetch .verify.json sidecar ─── parallel ───► Query SplatRegistry on-chain
       │                                          │
       └──────────────────┬───────────────────────┘
                          │
                          ▼
              Verify Ed25519 signatures
              (Web Crypto / @noble/ed25519)
                          │
                          ▼
              Render badge + provenance panel
```

## License

MIT