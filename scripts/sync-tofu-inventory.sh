#!/usr/bin/env bash
# Sync OpenTofu inventory to Ansible
#
# This script exports the OpenTofu-defined infrastructure (VMs, containers, IPs)
# to a JSON file that Ansible can dynamically load via load_tofu.yml
#
# Required environment variables (used by Ansible playbooks consuming this inventory):
#   PROXMOX_VE_HOSTNAME  - Proxmox VE host that Ansible will connect to
#   PROXMOX_SSH_KEY_PATH - Path to the SSH private key used for Proxmox access
#
# Usage:
#   ./scripts/sync-tofu-inventory.sh
#   TERRAFORM_DIR=/custom/path ./scripts/sync-tofu-inventory.sh
#
# This should be run after 'terragrunt apply' in terraform-proxmox to ensure
# Ansible has the latest infrastructure configuration.

set -euo pipefail

# Color output helpers
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Navigate to project root (parent of scripts directory)
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Path to OpenTofu infrastructure (configurable via environment variable)
TERRAFORM_DIR="${TERRAFORM_DIR:-${HOME}/git/terraform-proxmox/main}"

# Path to Ansible inventory file
INVENTORY_FILE="${PROJECT_ROOT}/inventory/tofu_inventory.json"

# Ensure OpenTofu directory exists
if [[ ! -d "${TERRAFORM_DIR}" ]]; then
  echo -e "${RED}ERROR: OpenTofu directory not found at ${TERRAFORM_DIR}${NC}" >&2
  exit 1
fi

# Ensure Ansible project directory exists
if [[ ! -d "${PROJECT_ROOT}" ]]; then
  echo -e "${RED}ERROR: Ansible project directory not found at ${PROJECT_ROOT}${NC}" >&2
  exit 1
fi

echo -e "${YELLOW}Exporting OpenTofu inventory...${NC}"
echo "  OpenTofu dir: ${TERRAFORM_DIR}"
echo "  Output file:   ${INVENTORY_FILE}"

# Change to OpenTofu directory and export inventory
if cd "${TERRAFORM_DIR}" && terragrunt output -json ansible_inventory > "${INVENTORY_FILE}"; then
  echo -e "${GREEN}✓ Inventory exported successfully${NC}"

  # Show summary of exported infrastructure
  echo -e "\n${YELLOW}Infrastructure Summary:${NC}"

  # Use Python to parse and display the JSON in a readable format
  python3 << 'PYTHON_EOF' "${INVENTORY_FILE}"
import json
import sys

try:
    with open(sys.argv[1]) as f:
        inventory = json.load(f)

        # Count resources
        containers = inventory.get('ansible_inventory', {}).get('containers', {})
        vms = inventory.get('ansible_inventory', {}).get('vms', {})
        splunk = inventory.get('ansible_inventory', {}).get('splunk_vm', {})

        print(f"  Containers: {len(containers)}")
        for name, details in containers.items():
            if isinstance(details, dict):
                print(f"    - {name}: {details.get('ip', 'N/A')}")

        print(f"  VMs: {len(vms)}")
        for name, details in vms.items():
            if isinstance(details, dict):
                print(f"    - {name}: {details.get('ip', 'N/A')}")

        splunk_vm_details = splunk.get('splunk')
        if isinstance(splunk_vm_details, dict):
            print(f"  Splunk VM:")
            print(f"    - {splunk_vm_details.get('hostname', 'splunk')}: {splunk_vm_details.get('ip', 'N/A')}")

except Exception as e:
    print(f"  (Could not parse inventory: {e})", file=sys.stderr)
PYTHON_EOF

  echo -e "\n${GREEN}Ansible can now use this inventory via 'load_tofu.yml'${NC}"
else
  echo -e "${RED}ERROR: Failed to export OpenTofu inventory${NC}" >&2
  exit 1
fi
