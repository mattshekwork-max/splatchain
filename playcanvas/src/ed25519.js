/**
 * Ed25519 signature verification for SplatChain sidecar data.
 *
 * Uses the Web Crypto API (SubtleCrypto) for Ed25519 verification.
 * Falls back to the @noble/ed25519 library if SubtleCrypto doesn't
 * support Ed25519 (older browsers).
 *
 * The Python SDK signs with PyNaCl (NaCl/libsodium Ed25519), which
 * produces standard Ed25519 signatures compatible with both Web Crypto
 * and @noble/ed25519.
 */

// Cache for the noble library (lazy-loaded)
let _noble = null;

/**
 * Verify an Ed25519 signature against a message object.
 *
 * The Python SDK signs over the JSON-serialized message (sorted keys,
 * no whitespace). We reconstruct the same canonical JSON here.
 *
 * @param {string} publicKeyHex — Ed25519 public key as hex string (64 chars)
 * @param {Object} messageObj — The message object (without the "signature" field)
 * @param {string} signatureHex — Ed25519 signature as hex string (128 chars)
 * @returns {Promise<boolean>} — true if signature is valid
 */
export async function verifyEd25519(publicKeyHex, messageObj, signatureHex) {
  if (!publicKeyHex || !signatureHex) return false;

  // Canonical JSON — same as Python SDK
  const message = canonicalJson(messageObj);
  const messageBytes = new TextEncoder().encode(message);

  // Convert hex to Uint8Array
  const sigBytes = hexToBytes(signatureHex);
  const pubKeyBytes = hexToBytes(publicKeyHex);

  // Try Web Crypto first (modern browsers)
  try {
    const key = await crypto.subtle.importKey(
      'raw',
      pubKeyBytes,
      { name: 'Ed25519', namedCurve: 'Ed25519' },
      false,
      ['verify'],
    );
    return await crypto.subtle.verify('Ed25519', key, sigBytes, messageBytes);
  } catch (e) {
    // Web Crypto doesn't support Ed25519 — fall back to @noble/ed25519
    console.info('[SplatChain] Web Crypto Ed25519 not supported, falling back to noble');
    return await verifyWithNoble(pubKeyBytes, messageBytes, sigBytes);
  }
}

/**
 * Verify using @noble/ed25519 as a fallback.
 */
async function verifyWithNoble(pubKeyBytes, messageBytes, sigBytes) {
  if (!_noble) {
    try {
      _noble = await import('@noble/ed25519');
    } catch (e) {
      console.error('[SplatChain] @noble/ed25519 not available. Install it for Ed25519 verification support.');
      return false;
    }
  }
  return await _noble.verify(sigBytes, messageBytes, pubKeyBytes);
}

// ── Utility ──────────────────────────────────────────────────────

/**
 * Canonical JSON — sorted keys, no whitespace.
 * Matches Python's json.dumps(obj, sort_keys=True, separators=(',', ':'))
 */
export function canonicalJson(obj) {
  return JSON.stringify(obj, Object.keys(obj).sort());
}

/**
 * Hex string to Uint8Array.
 */
export function hexToBytes(hex) {
  const clean = hex.replace(/^0x/, '');
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < clean.length; i += 2) {
    bytes[i / 2] = parseInt(clean.substring(i, i + 2), 16);
  }
  return bytes;
}

/**
 * Uint8Array to hex string.
 */
export function bytesToHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}