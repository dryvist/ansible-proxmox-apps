"""Reuse the Proxmox PCT SSH session across Homarr tasks."""

from ansible_collections.community.proxmox.plugins.connection import proxmox_pct_remote


# Keep a literal option schema so Ansible's documentation and config loaders
# can parse this local alias. Options are copied from the upstream plugin.
DOCUMENTATION = r"""
author: Nils Stein (@mietzen) <github.nstein@mailbox.org>
name: pct_remote_persistent
short_description: Run tasks in Proxmox LXC container instances using pct CLI via SSH
requirements:
  - paramiko
description:
  - Run commands or put/fetch files to an existing Proxmox LXC container using pct CLI via SSH.
  - Uses the Python SSH implementation (Paramiko) to connect to the Proxmox host.
options:
  remote_addr:
    description:
      - Address of the remote target.
    default: inventory_hostname
    type: string
    vars:
      - name: inventory_hostname
      - name: ansible_host
      - name: ansible_ssh_host
      - name: ansible_paramiko_host
  port:
    description: Remote port to connect to.
    type: int
    default: 22
    ini:
      - section: defaults
        key: remote_port
      - section: paramiko_connection
        key: remote_port
    env:
      - name: ANSIBLE_REMOTE_PORT
      - name: ANSIBLE_REMOTE_PARAMIKO_PORT
    vars:
      - name: ansible_port
      - name: ansible_ssh_port
      - name: ansible_paramiko_port
    keyword:
      - name: port
  remote_user:
    description:
      - User to login/authenticate as.
      - Can be set from the CLI via the C(--user) or C(-u) options.
    type: string
    vars:
      - name: ansible_user
      - name: ansible_ssh_user
      - name: ansible_paramiko_user
    env:
      - name: ANSIBLE_REMOTE_USER
      - name: ANSIBLE_PARAMIKO_REMOTE_USER
    ini:
      - section: defaults
        key: remote_user
      - section: paramiko_connection
        key: remote_user
    keyword:
      - name: remote_user
  password:
    description:
      - Secret used to either login the SSH server or as a passphrase for SSH keys that require it.
      - Can be set from the CLI via the C(--ask-pass) option.
    type: string
    vars:
      - name: ansible_password
      - name: ansible_ssh_pass
      - name: ansible_ssh_password
      - name: ansible_paramiko_pass
      - name: ansible_paramiko_password
  use_rsa_sha2_algorithms:
    description:
      - Whether or not to enable RSA SHA2 algorithms for pubkeys and hostkeys.
      - On paramiko versions older than 2.9, this only affects hostkeys.
      - For behavior matching paramiko<2.9 set this to V(false).
    vars:
      - name: ansible_paramiko_use_rsa_sha2_algorithms
    ini:
      - {key: use_rsa_sha2_algorithms, section: paramiko_connection}
    env:
      - {name: ANSIBLE_PARAMIKO_USE_RSA_SHA2_ALGORITHMS}
    default: true
    type: boolean
  host_key_auto_add:
    description: "Automatically add host keys to C(~/.ssh/known_hosts)."
    env:
      - name: ANSIBLE_PARAMIKO_HOST_KEY_AUTO_ADD
    ini:
      - key: host_key_auto_add
        section: paramiko_connection
    type: boolean
  look_for_keys:
    default: True
    description: "Set to V(false) to disable searching for private key files in C(~/.ssh/)."
    env:
      - name: ANSIBLE_PARAMIKO_LOOK_FOR_KEYS
    ini:
      - {key: look_for_keys, section: paramiko_connection}
    type: boolean
  proxy_command:
    default: ""
    description:
      - Proxy information for running the connection via a jumphost.
    type: string
    env:
      - name: ANSIBLE_PARAMIKO_PROXY_COMMAND
    ini:
      - {key: proxy_command, section: paramiko_connection}
    vars:
      - name: ansible_paramiko_proxy_command
  pty:
    default: True
    description: "C(sudo) usually requires a PTY, V(true) to give a PTY and V(false) to not give a PTY."
    env:
      - name: ANSIBLE_PARAMIKO_PTY
    ini:
      - section: paramiko_connection
        key: pty
    type: boolean
  record_host_keys:
    default: True
    description: "Save the host keys to a file."
    env:
      - name: ANSIBLE_PARAMIKO_RECORD_HOST_KEYS
    ini:
      - section: paramiko_connection
        key: record_host_keys
    type: boolean
  host_key_checking:
    description: "Set this to V(false) if you want to avoid host key checking by the underlying tools Ansible uses to connect to the host."
    type: boolean
    default: true
    env:
      - name: ANSIBLE_HOST_KEY_CHECKING
      - name: ANSIBLE_SSH_HOST_KEY_CHECKING
      - name: ANSIBLE_PARAMIKO_HOST_KEY_CHECKING
    ini:
      - section: defaults
        key: host_key_checking
      - section: paramiko_connection
        key: host_key_checking
    vars:
      - name: ansible_host_key_checking
      - name: ansible_ssh_host_key_checking
      - name: ansible_paramiko_host_key_checking
  use_persistent_connections:
    description: "This adapter always uses persistence; this option cannot disable it."
    type: boolean
    default: False
    env:
      - name: ANSIBLE_USE_PERSISTENT_CONNECTIONS
    ini:
      - section: defaults
        key: use_persistent_connections
  forward_agent:
    description: "Enable SSH agent forwarding."
    type: boolean
    default: False
    env:
      - name: ANSIBLE_PARAMIKO_FORWARD_AGENT
    ini:
      - section: paramiko_connection
        key: forward_agent
  banner_timeout:
    type: float
    default: 30
    description:
      - Configures, in seconds, the amount of time to wait for the SSH
        banner to be presented. This option is supported by paramiko
        version 1.15.0 or newer.
    ini:
      - section: paramiko_connection
        key: banner_timeout
    env:
      - name: ANSIBLE_PARAMIKO_BANNER_TIMEOUT
  timeout:
    type: int
    default: 10
    description: Number of seconds until the plugin gives up on failing to establish a TCP connection.
    ini:
      - section: defaults
        key: timeout
      - section: ssh_connection
        key: timeout
      - section: paramiko_connection
        key: timeout
    env:
      - name: ANSIBLE_TIMEOUT
      - name: ANSIBLE_SSH_TIMEOUT
      - name: ANSIBLE_PARAMIKO_TIMEOUT
    vars:
      - name: ansible_ssh_timeout
      - name: ansible_paramiko_timeout
    cli:
      - name: timeout
  lock_file_timeout:
    type: int
    default: 60
    description: Number of seconds until the plugin gives up on trying to write a lock file when writing SSH known host keys.
    vars:
      - name: ansible_lock_file_timeout
    env:
      - name: ANSIBLE_LOCK_FILE_TIMEOUT
  private_key_file:
    description:
      - Path to private key file to use for authentication.
    type: string
    ini:
      - section: defaults
        key: private_key_file
      - section: paramiko_connection
        key: private_key_file
    env:
      - name: ANSIBLE_PRIVATE_KEY_FILE
      - name: ANSIBLE_PARAMIKO_PRIVATE_KEY_FILE
    vars:
      - name: ansible_private_key_file
      - name: ansible_ssh_private_key_file
      - name: ansible_paramiko_private_key_file
    cli:
      - name: private_key_file
        option: "--private-key"
  vmid:
    description:
      - LXC Container ID
    type: int
    vars:
      - name: proxmox_vmid
  proxmox_become_method:
    description:
      - Become command used in proxmox
    type: str
    default: sudo
    vars:
      - name: proxmox_become_method
notes:
  - >
    When NOT using this plugin as root, you need to have a become mechanism,
    e.g. C(sudo), installed on Proxmox and setup so we can run it without prompting for the password.
    Inside the container, we need a shell, for example C(sh) and the C(cat) command to be available in the C(PATH) for this plugin to work.
"""


class Connection(proxmox_pct_remote.Connection):
    """Keep the upstream PCT transport open through Ansible's connection daemon."""

    transport = "pct_remote_persistent"
    force_persistence = True
