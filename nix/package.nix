{ lib, buildHomeAssistantComponent, home-assistant }:
let
  adbShell = home-assistant.python.pkgs.adb-shell;
in
buildHomeAssistantComponent {
  owner = "local";
  domain = "haier_tv";
  version = "0.1.0";
  src = ../custom_components/haier_tv;
  dependencies = [ adbShell ] ++ adbShell.optional-dependencies.async;
  meta = {
    description = "Native ADB control for Haier LE40AL88G31R1";
    license = lib.licenses.asl20;
  };
}
