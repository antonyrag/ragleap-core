# Changelog

All notable changes to `ragleap-ansible` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `ragleap_base` role: apt cache, base packages, a deploy user with key-only login, passwordless sudo validated with `visudo`, and unattended-upgrades.
- `playbooks/bootstrap.yml`, which targets only the group `ragleap_servers`.
- A check that rejects an SSH public key that is not a full OpenSSH key line, because a truncated key would lock the deploy user out once sshd hardening exists.
- Container test that runs the playbook twice in a throwaway Ubuntu 22.04 container and requires the second run to change nothing.

### Not yet implemented

- sshd hardening, firewall, Helm, k3s and chart installation. Nothing has been released.
