const hre = require("hardhat");

async function main() {
  console.log("Deploying SplatChain...");
  console.log(`Network: ${hre.network.name}`);

  const [deployer] = await hre.ethers.getSigners();
  console.log(`Deployer: ${deployer.address}`);
  
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log(`Balance: ${hre.ethers.formatEther(balance)} ETH`);

  if (balance === 0n) {
    console.error("ERROR: Deployer has no ETH!");
    process.exit(1);
  }

  const SplatRegistry = await hre.ethers.getContractFactory("SplatRegistry");
  const registry = await SplatRegistry.deploy();
  
  await registry.waitForDeployment();
  
  const address = await registry.getAddress();
  const chainId = (await hre.ethers.provider.getNetwork()).chainId;
  console.log(`\n✅ SplatRegistry deployed to: ${address}`);
  console.log(`   Owner: ${deployer.address}`);
  console.log(`   Chain ID: ${chainId}`);
  
  let explorerUrl;
  if (chainId === 11155111n) {
    explorerUrl = `https://sepolia.etherscan.io/address/${address}`;
    console.log(`   Explorer: ${explorerUrl}`);
  } else if (chainId === 84532n) {
    explorerUrl = `https://sepolia.basescan.org/address/${address}`;
    console.log(`   Explorer: ${explorerUrl}`);
  }
  
  // Verify deployment
  const totalAtt = await registry.totalAttestations();
  console.log(`   Total attestations: ${totalAtt}`);
  
  console.log(`\nAdd to your .env:`);
  console.log(`  SPLAT_REGISTRY_ADDRESS=${address}`);
  console.log(`  CHAIN_ID=${chainId}`);
  
  return address;
}

main()
  .then((address) => {
    console.log(`\nDeployment complete: ${address}`);
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });