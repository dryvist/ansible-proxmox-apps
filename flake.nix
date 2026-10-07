{
  description = "Development shell for Ansible Proxmox Apps";

  inputs.nix-devenv.url = "git+https://github.com/dryvist/nix-devenv.git?ref=develop";

  outputs = { nix-devenv, ... }: {
    devShells = builtins.mapAttrs (_: shells: {
      default = shells.ansible-apps;
    }) nix-devenv.devShells;
  };
}
