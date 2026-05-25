#!/bin/bash
options="  Power Off\n  Reboot\n  Suspend\n󰍃  Log Out\n  Lock"
chosen=$(echo -e "$options" | rofi -dmenu -i -p "  Power Menu" -theme-str 'window {width: 400px;}')
case "$chosen" in
    *"Power Off") systemctl poweroff ;;
    *"Reboot")    systemctl reboot ;;
    *"Suspend")   systemctl suspend ;;
    *"Log Out")   hyprctl dispatch exit ;;
    *"Lock")      hyprlock ;;
esac
