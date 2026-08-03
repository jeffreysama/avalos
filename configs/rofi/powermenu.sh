#!/bin/bash
# AvalOS Power Menu — detección automática de idioma vía $LANG
# Soporta: English · Español · 中文简体

LANG_CODE="${LANG%%_*}"   # "es_SV.UTF-8" → "es"

# SUGERENCIA (revisión externa, aplicada): cargar el tema explícito en
# vez de depender de que config.rasi sea el default activo del usuario.
# Ahora mismo rofi ya lo carga solo (config.rasi ES su path por defecto),
# pero esto blinda el powermenu para el día que AvalOS permita cambiar
# de tema — el menú de energía siempre va a usar Tokyo Night pase lo
# que pase con el tema "activo" del usuario en ese momento.
ROFI_THEME="$HOME/.config/rofi/config.rasi"

case "$LANG_CODE" in
  es)
    T_OFF="  Apagar"
    T_REBOOT="  Reiniciar"
    T_SUSPEND="  Suspender"
    T_LOGOUT="󰍃  Cerrar Sesión"
    T_LOCK="  Bloquear"
    T_TITLE="  Menú de Energía"
    ;;
  zh)
    T_OFF="  关机"
    T_REBOOT="  重启"
    T_SUSPEND="  睡眠"
    T_LOGOUT="󰍃  注销"
    T_LOCK="  锁屏"
    T_TITLE="  电源"
    ;;
  *)  # English (default)
    T_OFF="  Power Off"
    T_REBOOT="  Reboot"
    T_SUSPEND="  Suspend"
    T_LOGOUT="󰍃  Log Out"
    T_LOCK="  Lock"
    T_TITLE="  Power Menu"
    ;;
esac

# BUG-1 FIX: rofi sin -no-custom.
# Sin -no-custom el usuario puede escribir texto libre y pulsar Enter,
# ejecutando un match vacío y llegando al bloque final sin ejecutar nada
# (silencioso) o ejecutando el primer comando si chosen queda vacío.
# -no-custom impide seleccionar entradas que no estén en la lista.
chosen=$(printf '%s\n' "$T_LOCK" "$T_SUSPEND" "$T_LOGOUT" "$T_REBOOT" "$T_OFF" \
  | rofi -dmenu \
         -theme "$ROFI_THEME" \
         -i \
         -no-custom \
         -p "$T_TITLE" \
         -theme-str 'window {width: 220px;} listview {lines: 5;}')

# BUG-2 FIX: chosen vacío (usuario cerró rofi con Escape) no se manejaba.
# Sin este guard, el script continuaba y evaluaba todas las condiciones
# con una variable vacía, produciendo una salida silenciosa normal.
[[ -z "$chosen" ]] && exit 0

# BUG-3 FIX: acciones sin confirmación para apagar y reiniciar.
# Apagar y reiniciar son acciones destructivas — una pulsación accidental
# cierra todo el trabajo sin guardar. Se añade un segundo diálogo de
# confirmación solo para estas dos acciones.
_confirm() {
  local msg="$1"
  case "$LANG_CODE" in
    es) local yes="  Sí" no="  No" ;;
    zh) local yes="  是" no="  否" ;;
    *)  local yes="  Yes" no="  No" ;;
  esac
  local result
  result=$(printf '%s\n' "$yes" "$no" \
    | rofi -dmenu -theme "$ROFI_THEME" -i -no-custom -p "$msg" \
           -theme-str 'window {width: 180px;} listview {lines: 2;}')
  [[ "$result" == "$yes" ]]
}

if [[ "$chosen" == "$T_OFF" ]]; then
  case "$LANG_CODE" in
    es) _confirm "¿Apagar el equipo?" && systemctl poweroff ;;
    zh) _confirm "确定关机？" && systemctl poweroff ;;
    *)  _confirm "Power off?" && systemctl poweroff ;;
  esac
elif [[ "$chosen" == "$T_REBOOT" ]]; then
  case "$LANG_CODE" in
    es) _confirm "¿Reiniciar el equipo?" && systemctl reboot ;;
    zh) _confirm "确定重启？" && systemctl reboot ;;
    *)  _confirm "Reboot?" && systemctl reboot ;;
  esac
elif [[ "$chosen" == "$T_SUSPEND" ]]; then
  systemctl suspend
elif [[ "$chosen" == "$T_LOGOUT" ]]; then
  # WARN-05 FIX: detectar si la sesión corre bajo uwsm.
  # Con Hyprland 0.55 se recomienda uwsm como session manager.
  # "hyprctl dispatch exit" directo interfiere con el shutdown de uwsm/systemd.
  # Si uwsm está activo, usar "uwsm stop"; si no, hyprctl dispatch exit como fallback.
  #
  # BUG FIX: el nombre de servicio "uwsm-env-hyprland.service" no existe —
  # uwsm genera units con el patrón "wayland-wm@<desktop-entry-id>.service"
  # (escapado, ej. "wayland-wm@hyprland\x2duwsm.desktop.service"), que
  # depende de qué .desktop entry se usó para lanzar la sesión y por lo
  # tanto no tiene un nombre fijo verificable de antemano. Con el nombre
  # incorrecto, is-active SIEMPRE devolvía "inactive", así que el script
  # caía SIEMPRE al fallback hyprctl — exactamente lo que se quería evitar,
  # incluso corriendo bajo uwsm. uwsm expone su propio comando diseñado
  # para esto: "uwsm check is-active", que no depende de adivinar nombres.
  if command -v uwsm &>/dev/null && uwsm check is-active &>/dev/null; then
    uwsm stop
  else
    # FIX: "hyprctl dispatch exit" (sintaxis clásica) ya NO funciona con
    # raíz Lua — falla con "expected a dispatcher". Confirmado en vivo
    # durante pruebas y contra wiki.hypr.land/Configuring/Basics/Dispatchers
    # y el hyprland.lua de ejemplo oficial de hyprwm/Hyprland.
    hyprctl dispatch 'hl.dsp.exit()'
  fi
elif [[ "$chosen" == "$T_LOCK" ]]; then
  # BUG-4 FIX: hyprlock sin verificar si ya está corriendo.
  # Si el usuario llama al powermenu dos veces seguido, se abren dos
  # instancias de hyprlock solapadas. pidof evita la duplicación.
  pidof hyprlock || hyprlock
fi
