/**
 * SplatRegistry ABI — minimal subset for verification reads.
 * Full ABI lives in the Python SDK at splatchain/registry.py.
 */

export const REGISTRY_ABI = [
  {
    inputs: [
      { name: "inputHash", type: "bytes32" },
      { name: "modelHash", type: "bytes32" },
      { name: "captureMethod", type: "string" },
      { name: "modelFormat", type: "string" },
    ],
    name: "attest",
    outputs: [],
    stateMutability: "nonpayable",
    type: "function",
  },
  {
    inputs: [
      { name: "modelHash", type: "bytes32" },
    ],
    name: "getAttestation",
    outputs: [
      {
        components: [
          { name: "creator", type: "address" },
          { name: "inputHash", type: "bytes32" },
          { name: "modelHash", type: "bytes32" },
          { name: "captureMethod", type: "string" },
          { name: "modelFormat", type: "string" },
          { name: "timestamp", type: "uint256" },
          { name: "revoked", type: "bool" },
        ],
        name: "",
        type: "tuple",
      },
    ],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [
      { name: "modelHash", type: "bytes32" },
      { name: "reason", type: "string" },
    ],
    name: "revoke",
    outputs: [],
    stateMutability: "nonpayable",
    type: "function",
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: "modelHash", type: "bytes32" },
      { indexed: true, name: "inputHash", type: "bytes32" },
      { indexed: false, name: "creator", type: "address" },
    ],
    name: "SplatAttested",
    type: "event",
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: "modelHash", type: "bytes32" },
      { indexed: false, name: "reason", type: "string" },
    ],
    name: "SplatRevoked",
    type: "event",
  },
];