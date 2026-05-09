/**
 * SplatChain PlayCanvas Plugin — barrel export.
 *
 * import { SplatChainPlugin, VerificationStatus } from '@splatchain/playcanvas';
 */

export { SplatChainPlugin, VerificationStatus } from './splatchain-plugin.js';
export { computeModelHash, computeModelHashFromUrl, computeModelHashStream } from './hash.js';
export { verifyEd25519, canonicalJson, hexToBytes, bytesToHex } from './ed25519.js';
export { REGISTRY_ABI } from './registry-abi.js';