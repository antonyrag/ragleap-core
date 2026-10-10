#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip >/dev/null
python3 -m pip install -q "ansible-core>=2.16,<2.17"
cd /pkg
KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA test@example"
run() {
  ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
    -e ansible_become=false -e "{\"ragleap_base_deploy_ssh_public_key\": \"$KEY\"}"
}
echo "=== run 1"
run
echo "=== run 2 (must change nothing)"
out="$(run)"
echo "$out" | tail -6
echo "$out" | grep -q 'changed=0' || { echo "NOT IDEMPOTENT: second run changed something"; exit 1; }
echo "$out" | grep -q 'failed=0' || { echo "FAILED tasks on second run"; exit 1; }
echo "=== state checks"
id ragleap
test -f /home/ragleap/.ssh/authorized_keys
grep -c "$KEY" /home/ragleap/.ssh/authorized_keys
visudo -cf /etc/sudoers.d/90-ragleap
echo "=== a truncated key must be rejected"
if ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
  -e ansible_become=false -e '{"ragleap_base_deploy_ssh_public_key": "ssh-ed25519"}' >/tmp/bad.out 2>&1; then
  echo "BAD KEY WAS ACCEPTED"
  exit 1
fi
grep -q "must be a full OpenSSH" /tmp/bad.out
echo "truncated key rejected"
echo "container test passed"
