{ pkgs, ... }:
let
  haierTv = pkgs.callPackage ./package.nix { };
in
{
  services.home-assistant.customComponents = [ haierTv ];
}
