/**
 * SplatChain — PlayCanvas Verification Plugin
 *
 * Computes model_hash from loaded splat, queries SplatRegistry on-chain,
 * verifies Ed25519 signatures from sidecar, and renders a provenance
 * badge + detail panel in the PlayCanvas viewer.
 *
 * Usage:
 *   import { SplatChainPlugin } from './splat-verify-plugin.js';
 *   const plugin = new SplatChainPlugin(app, {
 *     registryAddress: '0x...',
 *     chainId: 8453,        // Base mainnet
 *     rpcUrl: 'https://mainnet.base.org',
 *   });
 *   await plugin.attach(splatEntity);
 */

import { REGISTRY_ABI } from './registry-abi.js';
import { computeModelHash } from './hash.js';
import { verifyEd25519 } from './ed25519.js';

// ── Status enum ──────────────────────────────────────────────────────────

export const VerificationStatus = Object.freeze({
  VERIFIED:            'verified',
  ATTESTED_UNVERIFIED: 'attested_unverified',
  REVOKED:             'revoked',
  UNVERIFIED:          'unverified',
  OFFLINE:             'offline',
  SIG_INVALID:         'sig_invalid',
});

const STATUS_META = {
  [VerificationStatus.VERIFIED]:            { icon: '✅', label: 'Verified Capture',    color: '#22c55e', bg: '#052e16' },
  [VerificationStatus.ATTESTED_UNVERIFIED]: { icon: '⚠️', label: 'Attested (unverified)', color: '#eab308', bg: '#422006' },
  [VerificationStatus.REVOKED]:             { icon: '🚫', label: 'Revoked',             color: '#ef4444', bg: '#450a0a' },
  [VerificationStatus.UNVERIFIED]:          { icon: '⚠️', label: 'Unverified',          color: '#f97316', bg: '#431407' },
  [VerificationStatus.OFFLINE]:             { icon: '📡', label: 'Offline',              color: '#6b7280', bg: '#1f2937' },
  [VerificationStatus.SIG_INVALID]:         { icon: '⚠️', label: 'Invalid Signature',   color: '#ef4444', bg: '#450a0a' },
};

const TIER_LABELS = ['—', 'Self-attested', 'Verified attester', 'Hardware-attested (TEE)'];

// ── Plugin class ──────────────────────────────────────────────────────────

export class SplatChainPlugin {
  /**
   * @param {pc.Application} app — PlayCanvas app instance
   * @param {Object} opts
   * @param {string} opts.registryAddress — SplatRegistry contract address
   * @param {number} opts.chainId — Chain ID (default: 8453 for Base)
   * @param {string} opts.rpcUrl — RPC URL for on-chain reads
   * @param {string} [opts.sidecarUrl] — URL to fetch .verify.json sidecar (auto-detected if omitted)
   * @param {boolean} [opts.showPanel] — Show provenance detail panel (default: true)
   * @param {HTMLElement} [opts.container] — DOM element to render badge into (default: document.body)
   */
  constructor(app, opts = {}) {
    this.app = app;
    this.registryAddress = opts.registryAddress;
    this.chainId = opts.chainId ?? 8453;
    this.rpcUrl = opts.rpcUrl ?? 'https://mainnet.base.org';
    this.sidecarUrl = opts.sidecarUrl ?? null;
    this.showPanel = opts.showPanel ?? true;
    this.container = opts.container ?? document.body;

    this._provider = null;
    this._contract = null;
    this._badgeEl = null;
    this._panelEl = null;
    this._result = null;

    // Block explorer base URL
    this._explorerBase = this.chainId === 8453
      ? 'https://basescan.org'
      : this.chainId === 84532
        ? 'https://sepolia.basescan.org'
        : 'https://etherscan.io';
  }

  // ── Attach to a loaded splat ──────────────────────────────────────────

  /**
   * Attach verification to a splat entity. Computes model hash from the
   * splat data, checks the registry, and verifies sidecar signatures.
   *
   * @param {pc.Entity} splatEntity — The PlayCanvas GSplat entity
   * @param {ArrayBuffer|Uint8Array} [splatData] — Raw splat file bytes (if available)
   * @param {string} [splatUrl] — URL the splat was loaded from (for sidecar auto-detect)
   */
  async attach(splatEntity, { splatData, splatUrl } = {}) {
    this.splatEntity = splatEntity;

    // 1. Compute model hash
    let modelHash;
    if (splatData) {
      modelHash = await computeModelHash(splatData);
    } else {
      // Try to get data from the splat asset
      const res = splatEntity?.resource;
      if (res?.data) {
        modelHash = await computeModelHash(res.data);
      } else {
        console.warn('[SplatChain] No splat data available for hashing');
        this._render(VerificationStatus.UNVERIFIED, { modelHash: null, message: 'No splat data' });
        return;
      }
    }

    // 2. Initialize on-chain connection
    await this._initContract();

    // 3. Fetch sidecar (parallel with chain query)
    const sidecarPromise = this._fetchSidecar(splatUrl);

    // 4. Query registry
    let onChain = null;
    try {
      onChain = await this._queryRegistry(modelHash);
    } catch (e) {
      console.warn('[SplatChain] Registry query failed:', e.message);
    }

    // 5. Wait for sidecar
    const sidecar = await sidecarPromise;

    // 6. Run verification logic
    this._result = this._verify(modelHash, onChain, sidecar);

    // 7. Render UI
    this._renderUI(this._result);
    return this._result;
  }

  // ── Internal: init contract ────────────────────────────────────────────

  async _initContract() {
    if (!this.registryAddress) {
      console.warn('[SplatChain] No registry address configured — skipping on-chain verification');
      return;
    }

    try {
      // Dynamic import — ethers is optional
      const { ethers } = await import('ethers');
      this._provider = new ethers.JsonRpcProvider(this.rpcUrl);
      this._contract = new ethers.Contract(this.registryAddress, REGISTRY_ABI, this._provider);
    } catch (e) {
      console.warn('[SplatChain] ethers not available — on-chain verification disabled. Install ethers.js for full functionality.');
      this._provider = null;
      this._contract = null;
    }
  }

  // ── Internal: query registry ────────────────────────────────────────────

  async _queryRegistry(modelHash) {
    if (!this._contract) return null;

    // modelHash needs to be bytes32 (left-pad 32-byte hex)
    const hashBytes32 = this._padBytes32(modelHash);

    try {
      const result = await this._contract.getAttestation(hashBytes32);
      if (!result || result.creator === '0x0000000000000000000000000000000000000000') {
        return null;
      }
      return {
        creator:     result.creator,
        inputHash:   result.inputHash,
        modelHash:   result.modelHash,
        captureMethod: result.captureMethod,
        modelFormat: result.modelFormat,
        timestamp:   Number(result.timestamp),
        revoked:     result.revoked,
      };
    } catch (e) {
      // Contract call failed — probably no attestation exists
      if (e.message?.includes('No attestation')) return null;
      throw e;
    }
  }

  // ── Internal: fetch sidecar ────────────────────────────────────────────

  async _fetchSidecar(splatUrl) {
    if (this.sidecarUrl) {
      try {
        const resp = await fetch(this.sidecarUrl);
        if (resp.ok) return await resp.json();
      } catch { /* fall through */ }
    }

    if (!splatUrl) return null;

    // Try common sidecar locations
    const candidates = [
      splatUrl.replace(/\.ply$/, '.ply.verify.json').replace(/\.splat$/, '.splat.verify.json'),
      splatUrl + '.verify.json',
    ];

    for (const url of candidates) {
      try {
        const resp = await fetch(url);
        if (resp.ok) return await resp.json();
      } catch { /* try next */ }
    }

    return null;
  }

  // ── Internal: verify logic ──────────────────────────────────────────────

  _verify(modelHash, onChain, sidecar) {
    // No chain data and no sidecar
    if (!onChain && !sidecar) {
      return {
        status: VerificationStatus.UNVERIFIED,
        modelHash,
        tier: 0,
        message: 'No provenance data found — unverified',
      };
    }

    // Revoked on-chain
    if (onChain?.revoked) {
      return {
        status: VerificationStatus.REVOKED,
        modelHash,
        inputHash: onChain.inputHash,
        onChain,
        tier: 0,
        message: 'Attestation has been revoked',
      };
    }

    // Verify sidecar signatures
    let sigValid = true;
    let captureAtt = sidecar?.capture_attestation ?? sidecar?.captureAttestation;
    let trainingReceipt = sidecar?.training_receipt ?? sidecar?.trainingReceipt;
    let inputHash = sidecar?.input_hash ?? sidecar?.inputHash;

    if (sidecar && captureAtt) {
      const devicePubKey = captureAtt.device_id ?? captureAtt.deviceId ?? captureAtt.devicePublicKey;
      const sig = captureAtt.signature;
      if (devicePubKey && sig) {
        const msgObj = { ...captureAtt };
        delete msgObj.signature;
        sigValid = sigValid && verifyEd25519(devicePubKey, msgObj, sig);
      }
    }

    if (sidecar && trainingReceipt) {
      const pipelinePubKey = trainingReceipt.pipeline_public_key ?? trainingReceipt.pipelinePublicKey;
      const sig = trainingReceipt.signature;
      if (pipelinePubKey && sig) {
        const msgObj = { ...trainingReceipt };
        delete msgObj.signature;
        sigValid = sigValid && verifyEd25519(pipelinePubKey, msgObj, sig);
      }
    }

    // Check input_hash binding
    if (sidecar && captureAtt && trainingReceipt) {
      const attInput = captureAtt.input_hash ?? captureAtt.inputHash;
      const receiptInput = trainingReceipt.input_hash ?? trainingReceipt.inputHash;
      if (attInput && receiptInput && attInput !== receiptInput) {
        return {
          status: VerificationStatus.SIG_INVALID,
          modelHash,
          inputHash,
          captureAtt,
          trainingReceipt,
          onChain,
          tier: 0,
          message: `Input hash mismatch: capture=${attInput.slice(0,16)}... receipt=${receiptInput.slice(0,16)}...`,
        };
      }
    }

    if (!sigValid) {
      return {
        status: VerificationStatus.SIG_INVALID,
        modelHash,
        inputHash,
        captureAtt,
        trainingReceipt,
        onChain,
        tier: 1,
        message: 'Signature verification failed',
      };
    }

    // All good
    if (onChain && sidecar) {
      const tier = this._getTier(onChain);
      return {
        status: VerificationStatus.VERIFIED,
        modelHash,
        inputHash,
        captureAtt,
        trainingReceipt,
        onChain,
        tier,
        message: 'Full provenance verified: on-chain attestation + valid signatures',
      };
    }

    if (onChain) {
      return {
        status: VerificationStatus.ATTESTED_UNVERIFIED,
        modelHash,
        inputHash: onChain.inputHash,
        onChain,
        tier: this._getTier(onChain),
        message: 'On-chain attestation found but no sidecar for signature verification',
      };
    }

    // Sidecar only, no chain
    return {
      status: VerificationStatus.ATTESTED_UNVERIFIED,
      modelHash,
      inputHash,
      captureAtt,
      trainingReceipt,
      tier: 0,
      message: 'Sidecar provenance found but no on-chain attestation',
    };
  }

  _getTier(onChain) {
    // Check if creator is an approved attester (Tier 2)
    // For now, default to Tier 1 (self-attested)
    // Tier detection requires additional contract reads
    return 1;
  }

  // ── Internal: render UI ─────────────────────────────────────────────────

  _renderUI(result) {
    const meta = STATUS_META[result.status] ?? STATUS_META[VerificationStatus.UNVERIFIED];

    // Remove existing badge
    this.destroy();

    // ── Badge ──
    const badge = document.createElement('div');
    badge.id = 'sv-badge';
    badge.innerHTML = `
      <span class="sv-icon">${meta.icon}</span>
      <span class="sv-label">${meta.label}</span>
    `;
    badge.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; z-index: 9999;
      background: ${meta.bg}; border: 1px solid ${meta.color}44;
      border-radius: 8px; padding: 10px 16px;
      display: flex; align-items: center; gap: 8px;
      cursor: ${this.showPanel ? 'pointer' : 'default'};
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px; color: ${meta.color};
      backdrop-filter: blur(8px);
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 2px 12px ${meta.color}22;
    `;
    badge.addEventListener('mouseenter', () => {
      badge.style.transform = 'scale(1.05)';
      badge.style.boxShadow = `0 4px 20px ${meta.color}44`;
    });
    badge.addEventListener('mouseleave', () => {
      badge.style.transform = 'scale(1)';
      badge.style.boxShadow = `0 2px 12px ${meta.color}22`;
    });
    if (this.showPanel) {
      badge.addEventListener('click', () => this._togglePanel());
    }
    this._badgeEl = badge;
    this.container.appendChild(badge);

    // ── Provenance Panel ──
    if (this.showPanel) {
      this._panelEl = this._createPanel(result, meta);
    }
  }

  _createPanel(result, meta) {
    const panel = document.createElement('div');
    panel.id = 'sv-panel';
    panel.style.cssText = `
      position: fixed; bottom: 70px; right: 20px; z-index: 10000;
      width: 340px; background: #0a0a0aee; border: 1px solid ${meta.color}44;
      border-radius: 12px; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px; color: #e5e5e5; overflow: hidden;
      transform: translateY(10px); opacity: 0; pointer-events: none;
      transition: transform 0.25s ease, opacity 0.25s ease;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      max-height: 80vh; overflow-y: auto;
    `;

    const txLink = result.onChain
      ? `<a href="${this._explorerBase}/tx/${result.onChain.txHash ?? ''}" target="_blank" 
           style="color: ${meta.color}; text-decoration: none;">View on-chain ↗</a>`
      : '';

    const captureInfo = result.captureAtt
      ? this._formatCaptureInfo(result.captureAtt)
      : '';

    const trainingInfo = result.trainingReceipt
      ? this._formatTrainingInfo(result.trainingReceipt)
      : '';

    panel.innerHTML = `
      <div style="background: ${meta.bg}; padding: 14px 16px; border-bottom: 1px solid ${meta.color}22;">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
          <span style="font-size:20px">${meta.icon}</span>
          <span style="font-size:15px; font-weight:600; color:${meta.color}">${meta.label}</span>
        </div>
        <div style="font-size:11px; color:#888;">${result.message}</div>
      </div>
      <div style="padding: 14px 16px;">
        <div style="margin-bottom: 12px;">
          <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Model Hash</div>
          <code style="font-size:11px; color:#aaa; word-break:break-all;">${result.modelHash ?? '—'}</code>
        </div>
        ${result.inputHash ? `
        <div style="margin-bottom: 12px;">
          <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Input Hash</div>
          <code style="font-size:11px; color:#aaa; word-break:break-all;">${result.inputHash}</code>
        </div>` : ''}
        <div style="margin-bottom: 12px;">
          <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Tier</div>
          <span style="font-size:13px; color:#ddd;">${TIER_LABELS[result.tier] ?? 'Unknown'}</span>
        </div>
        ${captureInfo}
        ${trainingInfo}
        ${result.onChain ? `
        <div style="margin-bottom: 12px;">
          <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Attester</div>
          <code style="font-size:11px; color:#aaa;">${this._shortenAddr(result.onChain.creator)}</code>
        </div>
        <div style="margin-bottom: 12px;">
          <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Attested</div>
          <span style="font-size:12px; color:#aaa;">${new Date(result.onChain.timestamp * 1000).toLocaleString()}</span>
        </div>
        ${txLink ? `<div style="margin-top:8px;">${txLink}</div>` : ''}
        ` : ''}
      </div>
    `;

    document.body.appendChild(panel);
    return panel;
  }

  _formatCaptureInfo(att) {
    const gps = att.gps ? `${att.gps.lat?.toFixed(4)}°${att.gps.lon?.toFixed(4)}°` : '';
    const method = att.capture_method ?? att.captureMethod ?? '';
    const ts = att.timestamp ? new Date(att.timestamp).toLocaleString() : '';
    const lines = [];
    if (method) lines.push(`<span style="color:#ddd">${method}</span>`);
    if (gps) lines.push(`<span style="color:#aaa">${gps}</span>`);
    if (ts) lines.push(`<span style="color:#888">${ts}</span>`);
    if (!lines.length) return '';
    return `
      <div style="margin-bottom: 12px;">
        <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Capture</div>
        ${lines.join('<br>')}
      </div>`;
  }

  _formatTrainingInfo(receipt) {
    const pipeline = receipt.pipeline ?? '';
    const count = receipt.gaussian_count ?? receipt.gaussianCount ?? '';
    const psnr = receipt.psnr ?? '';
    const lines = [];
    if (pipeline) lines.push(`<span style="color:#ddd">${pipeline}</span>`);
    if (count) lines.push(`<span style="color:#aaa">${count.toLocaleString()} gaussians</span>`);
    if (psnr) lines.push(`<span style="color:#888">PSNR: ${psnr} dB</span>`);
    if (!lines.length) return '';
    return `
      <div style="margin-bottom: 12px;">
        <div style="font-size:10px; text-transform:uppercase; letter-spacing:0.5px; color:#666; margin-bottom:4px;">Training</div>
        ${lines.join('<br>')}
      </div>`;
  }

  _togglePanel() {
    if (!this._panelEl) return;
    const open = this._panelEl.style.opacity === '1';
    if (open) {
      this._panelEl.style.transform = 'translateY(10px)';
      this._panelEl.style.opacity = '0';
      this._panelEl.style.pointerEvents = 'none';
    } else {
      this._panelEl.style.transform = 'translateY(0)';
      this._panelEl.style.opacity = '1';
      this._panelEl.style.pointerEvents = 'auto';
    }
  }

  // ── Utility ─────────────────────────────────────────────────────────────

  _padBytes32(hex) {
    // Ensure hash is 32 bytes (64 hex chars), left-padded with zeros
    const clean = hex.replace(/^0x/, '');
    return '0x' + clean.padStart(64, '0');
  }

  _shortenAddr(addr) {
    if (!addr) return '—';
    return `${addr.slice(0, 8)}...${addr.slice(-6)}`;
  }

  /** Detach badge and panel from DOM. */
  destroy() {
    this._badgeEl?.remove();
    this._panelEl?.remove();
    this._badgeEl = null;
    this._panelEl = null;
  }

  /** Get current verification result. */
  get result() { return this._result; }
}