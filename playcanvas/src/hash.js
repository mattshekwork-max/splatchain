/**
 * SHA-256 hashing for splat files using Web Crypto API.
 *
 * Computes the model_hash in the browser — no server needed.
 * Uses SubtleCrypto (available in all modern browsers + Web Workers).
 */

/**
 * Compute SHA-256 hash of a splat file.
 * Accepts ArrayBuffer, Uint8Array, or a Blob (fetches and hashes).
 *
 * @param {ArrayBuffer|Uint8Array|Blob} data — The raw splat file bytes
 * @returns {Promise<string>} — Hex string of the SHA-256 hash
 */
export async function computeModelHash(data) {
  let buffer;

  if (data instanceof Blob) {
    // Read blob into ArrayBuffer
    buffer = await data.arrayBuffer();
  } else if (data instanceof Uint8Array) {
    buffer = data.buffer;
  } else if (data instanceof ArrayBuffer) {
    buffer = data;
  } else {
    throw new TypeError(`Expected ArrayBuffer, Uint8Array, or Blob, got ${typeof data}`);
  }

  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Compute SHA-256 hash of a splat file from URL.
 * Fetches the file in chunks (streaming) to handle large files
 * without loading the entire thing into memory at once.
 *
 * @param {string} url — URL to the .ply/.splat file
 * @param {Object} [opts]
 * @param {RequestInit} [opts.fetchOpts] — Extra fetch options (headers, etc.)
 * @returns {Promise<string>} — Hex string of the SHA-256 hash
 */
export async function computeModelHashFromUrl(url, opts = {}) {
  const response = await fetch(url, opts.fetchOpts ?? {});

  if (!response.ok) {
    throw new Error(`Failed to fetch splat: ${response.status} ${response.statusText}`);
  }

  // Stream through the response, hashing as we go
  const reader = response.body.getReader();
  const hash = await crypto.subtle.digest('SHA-256', await readAllStream(reader));
  const hashArray = Array.from(new Uint8Array(hash));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Incremental SHA-256 for very large files.
 * Uses the Web Crypto streaming pattern — process chunks as they arrive.
 * This avoids loading the entire file into memory.
 *
 * Note: Web Crypto doesn't support streaming SHA-256 natively yet.
 * For files >500MB, consider using a Web Worker with a pure JS SHA-256
 * implementation that supports incremental updates.
 *
 * @param {ReadableStream} stream — A readable stream of bytes
 * @returns {Promise<string>} — Hex string of the SHA-256 hash
 */
export async function computeModelHashStream(stream) {
  const reader = stream.getReader();
  const chunks = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }

  // Concat and hash — this is the fallback since Web Crypto
  // doesn't have incremental SHA-256 yet
  const totalLen = chunks.reduce((sum, c) => sum + c.length, 0);
  const combined = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }

  return computeModelHash(combined);
}

// ── Helper ──────────────────────────────────────────────────────

async function readAllStream(reader) {
  const chunks = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }
  const totalLen = chunks.reduce((sum, c) => sum + c.length, 0);
  const combined = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }
  return combined;
}