"""
ui/html.py — HTML/CSS/JS del wizard del instalador, con el bridge
JS→Python ya apuntando a los nombres nuevos de ui.api.InstallerAPI.

Extraído programáticamente (nunca retipeado a mano) de skill_instalar_usb.py,
constante _HTML (líneas 628-2346, ~1719 líneas) + la función _build_html()
(líneas 5008-5049). El contenido es idéntico byte a byte al original EXCEPTO
por 10 líneas: las 9 llamadas window.pywebview.api.<nombre_viejo>(...) que
se renombraron a inglés para que coincidan con los métodos nuevos de
ui.api.InstallerAPI (ver el mapeo completo en el docstring de ese módulo).
set_language y on_ready ya estaban en inglés, no se tocaron. Verificado:
12 call-sites antes, 12 después, ningún nombre viejo sobrevive, y un diff
línea por línea confirmó que ninguna otra línea cambió.

CSS/markup/lógica de UI: sin cambios de ningún tipo respecto al original,
incluidos los comentarios de por qué (ej. el punto de inyección de
window._tzList/_localeList/_keymapList ANTES de 'use strict' para que las
IIFEs de initTZ()/initLocale()/initKeymap() las encuentren ya definidas).
"""
from __future__ import annotations

import json

import translations
from avalos_installer.core.config import (
    DEFAULT_HOSTNAME, DEFAULT_KEYMAP, DEFAULT_LOCALE, DEFAULT_TIMEZONE,
    KEYMAPS, LOCALES, TIMEZONES,
)
from avalos_installer.ui.assets import LOGO_B64

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>AvalOS — Instalador</title>
<style>
/* ── RESET ─────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; font-size: 13px; cursor: default; user-select: none; }

/* ── TOKYO NIGHT + PHOSPHOR TOKENS ─────────────────────────────────────── */
:root {
  --tn-bg:      #1a1b26;  --tn-bg2:     #16161e;  --tn-surface: #24283b;
  --tn-border:  #414868;  --tn-blue:    #7aa2f7;  --tn-blue2:   #2ac3de;
  --tn-cyan:    #7dcfff;  --tn-green:   #9ece6a;  --tn-yellow:  #e0af68;
  --tn-red:     #f7768e;  --tn-purple:  #bb9af7;  --tn-orange:  #ff9e64;
  --tn-text:    #c0caf5;  --tn-dim:     #565f89;  --tn-white:   #a9b1d6;
  --ph-bg:      #020c02;  --ph-surface: #030f03;  --ph-border:  #0a2a0a;
  --ph-green:   #00ff41;  --ph-dim:     #4a8a4a;  --ph-text:    #b8ffb8;
  --ph-cyan:    #00f5d4;  --ph-yellow:  #f5e642;  --ph-red:     #ff3c3c;
  --ph-orange:  #ff8c00;  --ph-muted:   #2a5c2a;  --ph-lo:      #003d0f;
  --font-ui: 'Segoe UI', system-ui, -apple-system, sans-serif;
  --font-mono: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  --r: 8px; --r-sm: 4px; --trans: 0.15s ease;
}

/* ── PAGES ──────────────────────────────────────────────────────────────── */
.lang-key-hint { position:absolute; right:12px; top:50%; transform:translateY(-50%);
  font-size:10px; color:#565f89; border:1px solid #414868; border-radius:4px;
  width:16px; height:16px; line-height:14px; text-align:center; }
.page { display: none; height: 100vh; width: 100vw; flex-direction: column; }
.page.active { display: flex; }
/* NOTA: no vuelvas a poner style="display:..." inline en ninguna .page —
   un display inline gana a .page/.page.active por especificidad de cascada
   y la página queda "pegada" visible aunque se le quite la clase active. */
#pg-lang { align-items: center; justify-content: center; height: 100%; gap: 0; }

/* ── SCROLLBAR ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--tn-border); border-radius: 3px; }

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 1: WELCOME
══════════════════════════════════════════════════════════════════════════ */
#pg-welcome {
  background: var(--tn-bg2);
  align-items: center; justify-content: center; gap: 28px;
}
.welcome-logo {
  font-family: var(--font-mono);
  color: var(--tn-blue); font-size: 11px; line-height: 1.25;
  text-align: center;
  text-shadow: 0 0 20px rgba(122,162,247,.4);
}
.welcome-sub {
  color: var(--tn-dim); font-family: var(--font-mono);
  font-size: 10px; letter-spacing: 3px; text-transform: uppercase;
  text-align: center; margin-top: -12px;
}
.welcome-desc {
  color: var(--tn-text); font-family: var(--font-ui);
  font-size: 14px; line-height: 1.7; text-align: center; max-width: 460px;
}
.welcome-desc strong { color: var(--tn-blue); }
.btn-primary {
  background: rgba(122,162,247,.12); border: 1px solid var(--tn-blue);
  color: var(--tn-blue); font-family: var(--font-ui); font-size: 13px;
  font-weight: 600; letter-spacing: 1px; padding: 11px 32px;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans);
}
.btn-primary:hover {
  background: rgba(122,162,247,.22);
  box-shadow: 0 0 16px rgba(122,162,247,.3);
}
.welcome-badges {
  display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;
}
.badge {
  font-family: var(--font-mono); font-size: 10px; padding: 3px 10px;
  border-radius: 20px; letter-spacing: .5px;
  border: 1px solid; opacity: .75;
}
.badge-blue   { color: var(--tn-blue);   border-color: var(--tn-blue); }
.badge-green  { color: var(--tn-green);  border-color: var(--tn-green); }
.badge-purple { color: var(--tn-purple); border-color: var(--tn-purple); }
.badge-cyan   { color: var(--tn-cyan);   border-color: var(--tn-cyan); }
/* Badges de snapshots en los botones de bootloader */
.badge-snap {
  font-size: 9px; padding: 2px 7px; border-radius: 20px;
  background: rgba(158,206,106,.15); color: #9ece6a;
  border: 1px solid rgba(158,206,106,.4);
  font-weight: 500; vertical-align: middle; margin-left: 5px;
}
.badge-warn {
  font-size: 9px; padding: 2px 7px; border-radius: 20px;
  background: rgba(224,175,104,.12); color: #e0af68;
  border: 1px solid rgba(224,175,104,.4);
  font-weight: 500; vertical-align: middle; margin-left: 5px;
}

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 2: CONFIG (disk + form)
══════════════════════════════════════════════════════════════════════════ */
#pg-config { background: var(--tn-bg); }

.cfg-topbar {
  height: 40px; background: var(--tn-bg2); border-bottom: 1px solid var(--tn-border);
  display: flex; align-items: center; padding: 0 16px; gap: 10px; flex-shrink: 0;
}
.cfg-topbar-title { color: var(--tn-blue); font-family: var(--font-mono); font-size: 12px; font-weight: 700; }
.cfg-topbar-step  { color: var(--tn-dim); font-size: 11px; margin-left: auto; }

.cfg-body { display: flex; flex: 1; overflow: hidden; }

/* Left: disk list */
.cfg-left {
  width: 330px; min-width: 280px; border-right: 1px solid var(--tn-border);
  display: flex; flex-direction: column; overflow: hidden;
}
.cfg-section-title {
  padding: 10px 14px 8px; border-bottom: 1px solid var(--tn-border); flex-shrink: 0;
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  text-transform: uppercase; color: var(--tn-dim);
}
#disk-list {
  flex: 1; overflow-y: auto; padding: 8px;
}
.disk-card {
  background: var(--tn-surface); border: 1px solid var(--tn-border);
  border-radius: var(--r-sm); padding: 9px 11px; margin-bottom: 6px;
  cursor: pointer; transition: border-color var(--trans);
}
.disk-card:hover { border-color: rgba(122,162,247,.5); }
.disk-card.selected {
  border-color: var(--tn-blue);
  box-shadow: 0 0 0 1px rgba(122,162,247,.2) inset;
}
.disk-card.boot-disk { opacity: .45; cursor: not-allowed; border-color: #2d2f44; }
.disk-name { color: var(--tn-blue); font-family: var(--font-mono); font-size: 13px; font-weight: 700; }
.disk-meta { color: var(--tn-dim); font-family: var(--font-mono); font-size: 10.5px; margin-top: 3px; line-height: 1.6; }
.disk-size { color: var(--tn-cyan); }
.dtag {
  display: inline-block; font-size: 9px; padding: 1px 5px;
  border-radius: 3px; letter-spacing: .4px; text-transform: uppercase;
  margin-left: 5px; vertical-align: middle; font-family: var(--font-mono);
}
.dtag-ssd  { background: #001829; color: var(--tn-cyan);   border: 1px solid #00304a; }
.dtag-hdd  { background: #1c1a00; color: var(--tn-yellow); border: 1px solid #3a3500; }
.dtag-boot { background: #1c1000; color: var(--tn-orange); border: 1px solid #3a2000; }
.dtag-sel  { background: rgba(122,162,247,.1); color: var(--tn-blue); border: 1px solid rgba(122,162,247,.3); }
.disk-warn { font-size: 10px; color: var(--tn-orange); margin-top: 3px; }

/* Right: form */
.cfg-right { flex: 1; overflow-y: auto; padding: 20px 24px; }
.cfg-form-wrap { max-width: 500px; margin: 0 auto; }

.form-section-title {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.2px;
  text-transform: uppercase; color: var(--tn-dim);
  margin-bottom: 14px; margin-top: 4px;
}

.form-row { display: flex; gap: 12px; }
.form-row .form-group { flex: 1; }

.form-group { margin-bottom: 14px; }
.form-group label {
  display: block; font-size: 11px; color: var(--tn-white);
  margin-bottom: 5px; font-weight: 500;
}
.form-group input,
.form-group select {
  width: 100%; padding: 8px 10px;
  background: var(--tn-surface); border: 1px solid var(--tn-border);
  border-radius: var(--r-sm); color: var(--tn-text);
  font-family: var(--font-mono); font-size: 12px;
  outline: none; transition: border-color var(--trans);
}
.form-group input:focus,
.form-group select:focus { border-color: var(--tn-blue); }
.form-group input.error  { border-color: var(--tn-red); }
.form-group input.ok     { border-color: var(--tn-green); }
.field-hint { font-size: 10px; color: var(--tn-dim); margin-top: 3px; display: block; }
.field-hint.err  { color: var(--tn-red); }
.field-hint.good { color: var(--tn-green); }

/* ── PASSWORD STRENGTH ──────────────────────────────────────────────── */
.pass-wrap { position: relative; }
.pass-wrap input { padding-right: 32px; }
.pass-toggle {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: var(--tn-dim); cursor: pointer;
  font-size: 13px; padding: 0; line-height: 1;
  transition: color var(--trans);
}
.pass-toggle:hover { color: var(--tn-text); }

.strength-bar-wrap {
  height: 3px; background: var(--tn-border); border-radius: 2px;
  margin-top: 5px; overflow: hidden;
}
.strength-bar {
  height: 100%; width: 0%; border-radius: 2px;
  transition: width 0.25s ease, background 0.25s ease;
}
.strength-bar.s0 { width: 0%; }
.strength-bar.s1 { width: 25%; background: var(--tn-red); }
.strength-bar.s2 { width: 50%; background: var(--tn-orange); }
.strength-bar.s3 { width: 75%; background: var(--tn-yellow); }
.strength-bar.s4 { width: 100%; background: var(--tn-green); }

.strength-reqs {
  display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 5px;
}
.req {
  font-family: var(--font-mono); font-size: 9.5px; color: var(--tn-dim);
  transition: color var(--trans);
}
.req.ok { color: var(--tn-green); }

.opts-row { display: flex; gap: 8px; }
.opt-btn {
  flex: 1; padding: 8px 10px; font-family: var(--font-mono); font-size: 11px;
  border-radius: var(--r-sm); cursor: pointer; transition: all var(--trans);
  border: 1px solid var(--tn-border); background: var(--tn-surface);
  color: var(--tn-dim); text-align: left; line-height: 1.4;
}
.opt-btn .opt-title { font-weight: 700; color: var(--tn-text); display: block; }
.opt-btn .opt-desc  { font-size: 9.5px; color: var(--tn-dim); }
.opt-btn.sel {
  border-color: var(--tn-blue); background: rgba(122,162,247,.1); color: var(--tn-blue);
}
.opt-btn.sel .opt-title { color: var(--tn-blue); }
.opt-btn.sel .opt-desc  { color: rgba(122,162,247,.6); }
.opt-btn:hover:not(.sel) { border-color: var(--tn-dim); }

.divider { border: none; border-top: 1px solid var(--tn-border); margin: 18px 0; }

#btn-instalar {
  width: 100%; padding: 12px 0; margin-top: 6px;
  font-family: var(--font-ui); font-size: 13px; font-weight: 700;
  letter-spacing: 1px; border-radius: var(--r); cursor: pointer;
  transition: all var(--trans);
  background: rgba(158,206,106,.12); border: 1px solid var(--tn-green);
  color: var(--tn-green); text-shadow: 0 0 8px rgba(158,206,106,.3);
}
#btn-instalar:hover {
  background: rgba(158,206,106,.22);
  box-shadow: 0 0 16px rgba(158,206,106,.25);
}
#btn-instalar:disabled { opacity: .35; cursor: not-allowed; }

#form-error {
  display: none; color: var(--tn-red); font-size: 11px;
  margin-top: 8px; text-align: center; padding: 6px;
  background: rgba(247,118,142,.08); border-radius: var(--r-sm);
  border: 1px solid rgba(247,118,142,.2);
}

/* ══════════════════════════════════════════════════════════════════════════
   PAGE 3: INSTALL  (phosphor terminal)
══════════════════════════════════════════════════════════════════════════ */
#pg-install {
  background: var(--ph-bg);
  font-family: var(--font-mono);
}
.blink { animation: blink 1.1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

#topbar {
  height: 38px; background: var(--ph-surface);
  border-bottom: 1px solid var(--ph-border);
  display: flex; align-items: center; padding: 0 12px; gap: 10px; flex-shrink: 0;
}
#topbar-title { color: var(--ph-green); font-size: 12px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  text-shadow: 0 0 8px rgba(0,255,65,.5); display: flex; align-items: center; gap: 8px; }
#status-label { font-size: 10px; color: var(--ph-dim); margin-left: 4px; letter-spacing: .5px; }
#topbar-right  { margin-left: auto; display: flex; gap: 8px; align-items: center; }
#internet-badge, #uefi-badge {
  font-size: 10px; padding: 2px 7px; border-radius: 2px;
  letter-spacing: .5px; border: 1px solid var(--ph-border);
  font-family: var(--font-mono);
}
.badge-ok  { color: var(--ph-green); border-color: var(--ph-lo) !important; }
.badge-err { color: var(--ph-red);   border-color: #3d0000 !important; }
.badge-warn{ color: var(--ph-yellow);border-color: #3d3000 !important; }

#inst-layout { display: flex; flex: 1; overflow: hidden; }

#inst-left {
  width: 290px; min-width: 250px; display: flex; flex-direction: column;
  border-right: 1px solid var(--ph-border); overflow: hidden;
}
.ph-section {
  font-size: 10px; letter-spacing: 1.2px; color: var(--ph-dim);
  text-transform: uppercase; padding: 8px 12px 6px;
  border-bottom: 1px solid var(--ph-border); flex-shrink: 0;
}
#info-panel { flex: 0 0 auto; padding: 7px 12px; border-bottom: 1px solid var(--ph-border); }
.info-row { display: flex; gap: 6px; font-size: 10.5px; margin-bottom: 2px; }
.info-key { color: var(--ph-dim); width: 80px; flex-shrink: 0; text-align: right; }
.info-val { color: var(--ph-text); }
.info-val.ok   { color: var(--ph-green); }
.info-val.err  { color: var(--ph-red); }
.info-val.warn { color: var(--ph-yellow); }

#steps-panel { flex: 1; overflow-y: auto; padding: 6px 10px; }
.step { display: flex; align-items: flex-start; gap: 8px; padding: 4px 0; border-bottom: 1px solid rgba(10,42,10,.3); }
.step:last-child { border-bottom: none; }
.step-icon  { width: 14px; flex-shrink: 0; font-size: 11px; }
.step-label { font-size: 11px; color: var(--ph-dim); line-height: 1.4; }
.step-detail{ font-size: 9.5px; color: var(--ph-dim); opacity: .7; margin-top: 1px; }
.step.done   .step-icon, .step.done   .step-label { color: var(--ph-green); }
.step.active .step-icon  { color: var(--ph-yellow); animation: blink .7s step-end infinite; }
.step.active .step-label { color: var(--ph-yellow); }
.step.error  .step-icon, .step.error  .step-label { color: var(--ph-red); }
.step.skip   .step-label { color: var(--ph-dim); text-decoration: line-through; }

#btn-area { flex-shrink: 0; padding: 8px 10px; border-top: 1px solid var(--ph-border); display: flex; gap: 6px; }
.action-btn {
  flex: 1; padding: 6px 0; font-family: var(--font-mono); font-size: 11px;
  letter-spacing: .8px; text-transform: uppercase; border-radius: 3px; cursor: pointer;
  transition: all var(--trans);
}
#btn-abort {
  background: #1a0000; border: 1px solid #5a0000; color: var(--ph-red);
}
#btn-abort:hover:not(:disabled) { background: #2d0000; }
#btn-abort:disabled { opacity: .3; cursor: not-allowed; }
#btn-retry {
  background: var(--ph-lo); border: 1px solid #1a6a1a; color: var(--ph-green); display: none;
}
#btn-retry:hover { background: rgba(0,255,65,.08); }

#inst-right { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#log-header {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px 6px;
  border-bottom: 1px solid var(--ph-border); flex-shrink: 0;
}
#log-title      { font-size: 10px; letter-spacing: 1.2px; color: var(--ph-dim); text-transform: uppercase; }
#log-lines-count{ font-size: 10px; color: var(--ph-dim); margin-left: auto; }
#log-wrap       { flex: 1; overflow-y: auto; padding: 8px 12px; }
#log { font-size: 11.5px; line-height: 1.65; white-space: pre-wrap; word-break: break-all; }
.log-cmd  { color: var(--ph-cyan); }
.log-ok   { color: var(--ph-green); }
.log-err  { color: var(--ph-red); }
.log-warn { color: var(--ph-yellow); }
.log-info { color: rgba(184,255,184,.55); }
.log-step { color: var(--ph-orange); font-weight: 700; }

#statusbar {
  height: 22px; background: var(--ph-surface); border-top: 1px solid var(--ph-border);
  display: flex; align-items: center; padding: 0 12px;
  font-size: 10.5px; color: var(--ph-dim); gap: 12px; flex-shrink: 0;
}
#statusbar-time { margin-left: auto; }
#progress-bar-wrap { position: absolute; bottom: 22px; left: 290px; right: 0; height: 2px; }
#progress-bar {
  height: 2px; background: var(--ph-green);
  width: 0%; transition: width .5s ease;
  box-shadow: 0 0 6px rgba(0,255,65,.6);
}

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: COUNTDOWN
══════════════════════════════════════════════════════════════════════════ */
.overlay {
  display: none; position: fixed; inset: 0; z-index: 900;
  background: rgba(0,0,0,.82);
  align-items: center; justify-content: center;
}
.overlay.show { display: flex; }
#ov-countdown .box {
  background: #1a0000; border: 2px solid var(--ph-red);
  border-radius: 8px; padding: 28px 36px; max-width: 460px;
  text-align: center; box-shadow: 0 0 40px rgba(255,60,60,.3);
  font-family: var(--font-mono);
}
#cd-title   { color: var(--ph-red); font-size: 15px; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 12px; }
#cd-body    { color: var(--ph-text); font-size: 12px; line-height: 1.8; margin-bottom: 14px; }
#cd-num     { color: var(--ph-red); font-size: 42px; font-weight: 700; letter-spacing: 2px; }
#cd-hint    { color: var(--ph-dim); font-size: 10.5px; margin-top: 8px; }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: ELEGIR MIRROR
══════════════════════════════════════════════════════════════════════════ */
#ov-mirror .box {
  background: var(--tn-surface); border: 1px solid var(--tn-yellow);
  border-radius: 8px; padding: 28px 36px; max-width: 520px; text-align: center;
  box-shadow: 0 0 40px rgba(224,175,104,.2); font-family: var(--font-ui);
}
#mirror-title   { color: var(--tn-yellow); font-size: 16px; font-weight: 700; letter-spacing: 1px; margin-bottom: 12px; }
#mirror-body    { color: var(--tn-text); font-size: 12px; line-height: 1.7; margin-bottom: 10px; }
#mirror-detalle { color: var(--tn-dim); font-size: 10.5px; font-family: var(--font-mono); line-height: 1.6; margin-bottom: 18px; word-break: break-word; }
.mirror-btns    { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.mirror-btns button {
  font-family: var(--font-mono); font-size: 10.5px; letter-spacing: .5px;
  border-radius: 6px; padding: 10px 14px; cursor: pointer; transition: .15s;
}
#btn-mirror-aceptar {
  background: rgba(158,206,106,.1); border: 1px solid var(--tn-green); color: var(--tn-green);
}
#btn-mirror-aceptar:hover { background: rgba(158,206,106,.2); }
#btn-mirror-rechazar {
  background: rgba(122,162,247,.1); border: 1px solid var(--tn-blue); color: var(--tn-blue);
}
#btn-mirror-rechazar:hover { background: rgba(122,162,247,.2); }
#btn-mirror-reintentar {
  background: rgba(224,175,104,.1); border: 1px solid var(--tn-yellow); color: var(--tn-yellow);
}
#btn-mirror-reintentar:hover { background: rgba(224,175,104,.2); }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: ERROR FATAL
══════════════════════════════════════════════════════════════════════════ */
#ov-error .box {
  background: var(--tn-surface); border: 1px solid var(--tn-red);
  border-radius: 8px; padding: 28px 36px; max-width: 480px; text-align: center;
  box-shadow: 0 0 40px rgba(247,118,142,.2); font-family: var(--font-ui);
}
#err-title { color: var(--tn-red); font-size: 16px; font-weight: 700; letter-spacing: 1px; margin-bottom: 12px; }
#err-msg   { color: var(--tn-text); font-size: 12px; line-height: 1.7; margin-bottom: 16px; }
#err-hint  { color: var(--tn-dim); font-size: 10.5px; margin-bottom: 16px; font-family: var(--font-mono); }
#btn-err-close {
  background: rgba(247,118,142,.1); border: 1px solid var(--tn-red); color: var(--tn-red);
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px;
  text-transform: uppercase; padding: 7px 20px; border-radius: var(--r-sm);
  cursor: pointer; transition: all var(--trans);
}
#btn-err-close:hover { background: rgba(247,118,142,.2); }

/* ══════════════════════════════════════════════════════════════════════════
   OVERLAY: DONE
══════════════════════════════════════════════════════════════════════════ */
#ov-done .box {
  background: var(--tn-surface); border: 1px solid var(--tn-green);
  border-radius: 12px; padding: 36px 44px; max-width: 520px; text-align: center;
  box-shadow: 0 0 48px rgba(158,206,106,.18); font-family: var(--font-ui);
}
#done-icon  { font-size: 52px; margin-bottom: 12px; }
#done-title { color: var(--tn-green); font-size: 20px; font-weight: 700; margin-bottom: 8px; }
#done-sub   { color: var(--tn-text); font-size: 12.5px; line-height: 1.75; margin-bottom: 8px; }
#done-info  { color: var(--tn-dim); font-size: 10.5px; line-height: 1.7;
  font-family: var(--font-mono); margin-bottom: 20px;
  background: var(--tn-bg2); border-radius: var(--r-sm);
  padding: 10px 14px; text-align: left; }
#done-info strong { color: var(--tn-blue); }
.done-btns { display: flex; gap: 10px; justify-content: center; }
.done-btns button {
  padding: 10px 24px; font-family: var(--font-ui); font-size: 12px; font-weight: 600;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans); letter-spacing: .5px;
}
#btn-reboot {
  background: rgba(158,206,106,.14); border: 1px solid var(--tn-green); color: var(--tn-green);
}
#btn-reboot:hover { background: rgba(158,206,106,.26); }
#btn-view-log {
  background: rgba(122,162,247,.14); border: 1px solid var(--tn-blue); color: var(--tn-blue);
}
#btn-view-log:hover { background: rgba(122,162,247,.26); }
#btn-close-done {
  background: var(--tn-surface); border: 1px solid var(--tn-border); color: var(--tn-dim);
}
#btn-close-done:hover { color: var(--tn-text); border-color: var(--tn-white); }

/* Botón flotante "← Volver" — solo visible mientras se está viendo el log
   después de haber cerrado el overlay de "instalación completada" (ver
   funciones verLog()/volverADone() en el bloque de JavaScript de más
   abajo). display:none es el estado normal; JS le agrega .show cuando
   corresponde. */
#btn-back-to-done {
  display: none; position: fixed; top: 16px; right: 16px; z-index: 50;
  padding: 8px 18px; font-family: var(--font-ui); font-size: 11.5px; font-weight: 600;
  border-radius: var(--r); cursor: pointer; transition: all var(--trans); letter-spacing: .5px;
  background: var(--tn-surface); border: 1px solid var(--tn-green); color: var(--tn-green);
  box-shadow: 0 2px 16px rgba(0,0,0,.35);
}
#btn-back-to-done.show { display: block; }
#btn-back-to-done:hover { background: rgba(158,206,106,.14); }
</style>
<script>
(function () {
  var overlay = null;
  var shown = {};
  function showJsError(msg) {
    if (shown[msg]) return;
    shown[msg] = true;
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'js-error-overlay';
      overlay.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
        'background:#3a0d0d;color:#ff9494;font:11px/1.5 monospace;' +
        'padding:8px 12px;max-height:38vh;overflow:auto;white-space:pre-wrap;' +
        'border-bottom:2px solid #ff5555;';
      (document.body || document.documentElement).appendChild(overlay);
    }
    var line = document.createElement('div');
    line.textContent = msg;
    overlay.appendChild(line);
  }
  window.__showJsError = showJsError;
  window.addEventListener('error', function (e) {
    showJsError('JS ERROR: ' + e.message + '  @' + (e.filename || '?') + ':' + e.lineno + ':' + e.colno);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    showJsError('PROMISE REJECTION: ' + (r && r.message ? r.message : String(r)));
  });
})();
</script>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 0 — LANGUAGE SELECTION
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-lang" class="page active">
  <div style="font-size:32px;font-weight:700;color:#c0caf5;letter-spacing:0.04em;
              margin-bottom:6px;">AvalOS</div>
  <div style="font-size:12px;color:#565f89;letter-spacing:0.14em;margin-bottom:40px;">
    INSTALLER · INSTALADOR · 安装程序
  </div>
  <div style="display:flex;flex-direction:column;gap:12px;width:260px;">
    <button data-lang="en" onclick="chooseLang('en')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇺🇸&nbsp; English
      <span class="lang-key-hint">1</span>
    </button>
    <button data-lang="es" onclick="chooseLang('es')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇪🇸&nbsp; Español
      <span class="lang-key-hint">2</span>
    </button>
    <button data-lang="zh" onclick="chooseLang('zh')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇨🇳&nbsp; 中文简体
      <span class="lang-key-hint">3</span>
    </button>
    <button data-lang="ja" onclick="chooseLang('ja')"
      style="padding:14px 0;font-size:15px;background:#24283b;color:#c0caf5;
             border:1.5px solid #414868;border-radius:8px;cursor:pointer;
             transition:border-color .15s,background .15s;position:relative;"
      onmouseover="this.style.borderColor='#7aa2f7';this.style.background='#1e2035'"
      onmouseout="this.style.borderColor='#414868';this.style.background='#24283b'">
      🇯🇵&nbsp; 日本語
      <span class="lang-key-hint">4</span>
    </button>
  </div>
  <div style="font-size:10px;color:#414868;letter-spacing:0.08em;margin-top:16px;">
    1‑4 · ↑↓ + Enter
  </div>
  <div id="lang-warning-box"
    style="margin-top:28px;max-width:340px;text-align:center;padding:10px 14px;
           background:rgba(224,175,104,0.08);border:1px solid rgba(224,175,104,0.25);
           border-radius:8px;">
    <span data-i18n="lang-warning"
      style="font-size:11px;color:#e0af68;line-height:1.6;">
      ⚠  UI language pack only · Mirrors optimized for US, MX &amp; GT
      — may be slow for mainland China or distant regions.
    </span>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 1 — WELCOME
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-welcome" class="page">
  <img id="avalos-logo" src="data:image/png;base64,LOGO_PLACEHOLDER"
       style="width:110px;height:110px;object-fit:contain;margin-bottom:-8px;
              border-radius:16px;box-shadow:0 0 18px 4px rgba(122,162,247,.35);">
  <pre class="welcome-logo" style="display:none;">
     _             _  ___  ____
    / \__   ____ _| |/ _ \/ ___|
   / _ \ \ / / _` | | | | \___ \
  / ___ \ V / (_| | | |_| |___) |
 /_/   \_\_/ \__,_|_|\___/|____/</pre>
  <div class="welcome-sub" data-i18n="welcome-sub">Arch Linux · Hyprland · Wayland · Tokyo Night</div>
  <div class="welcome-desc">
    <span data-i18n="welcome-desc">Bienvenido al instalador de <strong>AvalOS</strong>.<br>Este asistente configurará e instalará el sistema en el disco de tu elección.</span>
  </div>
  <div class="welcome-badges">
    <span class="badge badge-blue">Arch Linux (rolling)</span>
    <span class="badge badge-purple">Hyprland</span>
    <span class="badge badge-green">Wayland</span>
    <span class="badge badge-cyan">Tokyo Night</span>
    <span class="badge badge-blue">SDDM · PipeWire · AMD GPU</span>
  </div>
  <button class="btn-primary" onclick="showPage('config')" data-i18n="btn-start">Comenzar instalación →</button>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 2 — CONFIG  (disco + formulario)
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-config" class="page">
  <div class="cfg-topbar">
    <span class="cfg-topbar-title" data-i18n="topbar">● AvalOS Installer</span>
    <span id="cfg-step-hint" class="cfg-topbar-step" data-i18n="step-hint">Selecciona disco y configura el sistema</span>
  </div>
  <div class="cfg-body">

    <!-- LEFT: discos -->
    <div class="cfg-left">
      <div class="cfg-section-title" data-i18n="sec-disk">▸ Disco de destino</div>
      <div id="auto-partition-warning" style="
        font-family:var(--font-mono); font-size:10px; padding:8px 12px;
        background:rgba(247,118,142,.08); border-bottom:1px solid rgba(247,118,142,.25);
        color:var(--tn-red); line-height:1.5; flex-shrink:0;
        display:flex; align-items:center; justify-content:space-between; gap:10px;">
        <span data-i18n="warn-auto-partition">⚠ El particionado automático borra <strong>todo</strong> el disco elegido sin posibilidad de deshacer. Si prefieres controlarlo tú mismo, usa el modo manual.</span>
        <button id="btn-manual-mode" onclick="abrirModoManual()" data-i18n="btn-manual-mode"
          style="flex-shrink:0;padding:6px 12px;font-size:10px;background:#24283b;color:#c0caf5;
                 border:1px solid var(--tn-red);border-radius:6px;cursor:pointer;white-space:nowrap;">
          Modo manual
        </button>
      </div>
      <div id="live-disk-banner" data-i18n="disk-current-unavailable" style="
        font-family:var(--font-mono); font-size:10px; padding:8px 12px;
        background:rgba(224,175,104,.07); border-bottom:1px solid rgba(224,175,104,.2);
        color:var(--tn-yellow); display:none; line-height:1.5; flex-shrink:0;">
        ⚠ El <strong>Disco actual</strong> no está disponible como destino
        porque es el disco donde se ejecuta este live ISO.
      </div>
      <div id="manual-root-picker" style="
        font-family:var(--font-mono); font-size:10px; padding:10px 12px;
        background:rgba(122,162,247,.07); border-bottom:1px solid rgba(122,162,247,.25);
        color:var(--tn-text); display:none; flex-direction:column; gap:6px; flex-shrink:0;">
        <span data-i18n="manual-pick-root-label">Se detectó más de una partición de datos. Elegí cuál usar como root:</span>
        <div style="display:flex; gap:8px; align-items:center;">
          <select id="manual-root-select" style="
            flex:1; padding:6px 8px; background:#1a1b26; color:#c0caf5;
            border:1px solid rgba(122,162,247,.4); border-radius:6px;
            font-family:var(--font-mono); font-size:10px;"></select>
          <button id="btn-confirm-manual-root" onclick="confirmarRootManual()" data-i18n="btn-confirm-root"
            style="flex-shrink:0;padding:6px 12px;font-size:10px;background:#24283b;color:#c0caf5;
                   border:1px solid var(--tn-blue);border-radius:6px;cursor:pointer;white-space:nowrap;">
            Confirmar
          </button>
        </div>
      </div>
      <div id="disk-list">
        <div style="padding:14px;color:var(--tn-dim);font-family:var(--font-mono);font-size:11px;">
          <span data-i18n="disk-detecting-placeholder">Detectando discos…</span>
        </div>
      </div>
    </div>

    <!-- RIGHT: formulario -->
    <div class="cfg-right">
      <div class="cfg-form-wrap">

        <div class="form-section-title" data-i18n="sec-user">▸ Cuenta de usuario</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-user">Nombre de usuario</label>
            <input id="f-user" type="text" placeholder="johndoe"
                   oninput="sanitizeUser(this)" autocomplete="off" spellcheck="false">
            <span class="field-hint" id="hint-user" data-i18n="hint-username">Solo letras minúsculas, números y guiones</span>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-pass">Contraseña</label>
            <div class="pass-wrap">
              <input id="f-pass" type="password" placeholder="••••••••" oninput="checkPass()">
              <button class="pass-toggle" type="button" onclick="togglePass('f-pass','pt-1')" id="pt-1" data-i18n-title="lbl-show-hide" title="Mostrar/ocultar">👁</button>
            </div>
            <div class="strength-bar-wrap"><div class="strength-bar s0" id="strength-bar"></div></div>
            <div class="strength-reqs" id="strength-reqs">
              <span class="req" id="req-len" data-i18n="req-len-x">✗ 8+ caracteres</span>
              <span class="req" id="req-upper" data-i18n="req-upper-x">✗ mayúscula</span>
              <span class="req" id="req-lower" data-i18n="req-lower-x">✗ minúscula</span>
              <span class="req" id="req-num" data-i18n="req-num-x">✗ número</span>
              <span class="req" id="req-sym" data-i18n="req-sym-x">✗ símbolo</span>
            </div>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-confirm-pass">Confirmar contraseña</label>
            <div class="pass-wrap">
              <input id="f-pass2" type="password" placeholder="••••••••" oninput="checkPass()">
              <button class="pass-toggle" type="button" onclick="togglePass('f-pass2','pt-2')" id="pt-2" data-i18n-title="lbl-show-hide" title="Mostrar/ocultar">👁</button>
            </div>
            <span class="field-hint" id="hint-pass"></span>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-host">▸ Nombre del equipo</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-hostname">Hostname</label>
            <input id="f-host" type="text" placeholder="mi-pc"
                   oninput="sanitizeHost(this)" autocomplete="off" spellcheck="false">
            <span class="field-hint">Identificador en la red. Ej: avalos-pc</span>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-timezone">Zona horaria</label>
            <select id="f-tz"></select>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-lang">▸ Idioma y teclado</div>

        <div class="form-row">
          <div class="form-group">
            <label data-i18n="lbl-locale">Locale del sistema</label>
            <select id="f-locale"></select>
            <span class="field-hint">Idioma de mensajes, fechas y formatos del sistema</span>
          </div>
          <div class="form-group">
            <label data-i18n="lbl-keymap">Distribución de teclado</label>
            <select id="f-keymap"></select>
            <span class="field-hint" data-i18n="hint-keymap">Mapa de teclas para la consola y sesión</span>
          </div>
        </div>

        <hr class="divider">
        <div class="form-section-title" data-i18n="sec-advanced">▸ Opciones avanzadas</div>

        <div class="form-group">
          <label data-i18n="lbl-bootloader">Bootloader</label>
          <div class="opts-row">
            <button class="opt-btn sel" id="opt-bl-grub" onclick="selBootloader('grub')">
              <span class="opt-title">GRUB <span class="badge-snap" data-i18n="badge-snap-yes">✦ Snapshots</span></span>
              <span class="opt-desc" data-i18n="opt-grub-desc">Universal. BIOS + UEFI, dual-boot. Menú de snapshots Btrfs en el arranque.</span>
            </button>
            <button class="opt-btn" id="opt-bl-sd" onclick="selBootloader('sd-boot')">
              <span class="opt-title">systemd-boot <span class="badge-warn" data-i18n="badge-snap-no">⚠ Sin snapshots en boot</span></span>
              <span class="opt-desc" data-i18n="opt-sdboot-desc">Solo UEFI, rápido. Snapshots disponibles vía terminal, sin menú visual en el arranque.</span>
            </button>
            <button class="opt-btn" id="opt-bl-refind" onclick="selBootloader('refind')">
              <span class="opt-title">rEFInd <span class="badge-warn" data-i18n="badge-snap-no">⚠ Sin snapshots en boot</span></span>
              <span class="opt-desc" data-i18n="opt-refind-desc">Solo UEFI. Detecta kernels automáticamente. Snapshots requieren configuración manual.</span>
            </button>
            <button class="opt-btn" id="opt-bl-none" onclick="selBootloader('none')">
              <span class="opt-title" data-i18n="opt-no-boot">Sin bootloader</span>
              <span class="opt-desc">Omitir. Ya tengo un gestor de arranque instalado.</span>
            </button>
          </div>
        </div>

        <!-- Panel de advertencia snapshots — visible solo con sd-boot o rEFInd -->
        <div id="snap-boot-warning" style="display:none; margin:10px 0 0 0;
             background:rgba(224,175,104,0.10); border:1.5px solid #e0af68;
             border-radius:10px; padding:12px 16px; font-size:12.5px; line-height:1.7;
             color:#e0af68;">
        </div>

        <div class="form-group" style="margin-top:14px;">
          <label data-i18n="lbl-install-type">Tipo de instalación</label>
          <div class="opts-row">
            <button class="opt-btn sel" id="opt-modo-disco" onclick="selModo('disco', true)">
              <span class="opt-title" data-i18n="opt-pc">💾 PC / HDD / SSD</span>
              <span class="opt-desc" data-i18n="opt-pc-desc">Btrfs con subvolúmenes — snapshots automáticos, rollback desde GRUB.</span>
            </button>
            <button class="opt-btn" id="opt-modo-usb" onclick="selModo('usb', true)">
              <span class="opt-title" data-i18n="opt-usb">🔌 USB Persistente</span>
              <span class="opt-desc" data-i18n="opt-usb-desc">ext4 sin journal + noatime — minimiza escrituras en pendrive.</span>
            </button>
          </div>
        </div>

        <!-- ── Opciones adicionales ─────────────────────────────────── -->
        <div class="form-group" style="margin-top:10px;">
          <label data-i18n="lbl-extras">Extras</label>
          <div style="display:flex;flex-direction:column;gap:8px;margin-top:6px;">
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;
                          background:var(--tn-bg2);border:1px solid var(--tn-border);
                          border-radius:8px;padding:9px 12px;">
              <input type="checkbox" id="chk-gaming" onchange="window._installGaming=this.checked"
                     style="width:15px;height:15px;accent-color:var(--tn-blue);flex-shrink:0;">
              <span>
                <span class="opt-title" style="font-size:12.5px;" data-i18n="chk-gaming-title">🎮 Gaming</span>
                <span class="opt-desc" style="display:block;margin-top:2px;" data-i18n="chk-gaming-desc">Steam · Wine · DXVK · VKD3D · GameMode · MangoHUD · Lutris · Proton-GE (~2.5 GB extra)</span>
              </span>
            </label>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;
                          background:var(--tn-bg2);border:1px solid var(--tn-border);
                          border-radius:8px;padding:9px 12px;">
              <input type="checkbox" id="chk-bore" onchange="window._installBore=this.checked"
                     style="width:15px;height:15px;accent-color:var(--tn-blue);flex-shrink:0;">
              <span>
                <span class="opt-title" style="font-size:12.5px;" data-i18n="chk-bore-title">⚡ Scheduler BORE</span>
                <span class="opt-desc" style="display:block;margin-top:2px;" data-i18n="chk-bore-desc">Kernel linux-avalos-bore — mejor respuesta en juegos. Requiere CPU con AVX2 (x86-64-v3+); si no es compatible, se ignora y se usa el kernel estándar.</span>
              </span>
            </label>
          </div>
        </div>

        <button id="btn-instalar" onclick="validarEIniciar()">
          <span data-i18n="btn-install">▶ Instalar AvalOS</span>
        </button>
        <div id="form-error"></div>
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     PAGE 3 — INSTALLATION LOG
═══════════════════════════════════════════════════════════════════ -->
<div id="pg-install" class="page">
  <div id="topbar">
    <div id="topbar-title">
      <span class="blink">▮</span> AvalOS — Instalador
    </div>
    <span id="status-label">inicializando…</span>
    <div id="topbar-right">
      <span id="internet-badge" class="badge-warn">NET ···</span>
      <span id="uefi-badge" class="badge-warn">···</span>
    </div>
  </div>

  <div id="inst-layout">

    <div id="inst-left">
      <div class="ph-section">▸ Info del sistema</div>
      <div id="info-panel">
        <div class="info-row"><span class="info-key">Disco:</span><span id="iv-dest" class="info-val warn">—</span></div>
        <div class="info-row"><span class="info-key">Arranque:</span><span id="iv-boot" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Microcode:</span><span id="iv-ucode" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Internet:</span><span id="iv-net" class="info-val warn">verif…</span></div>
        <div class="info-row"><span class="info-key">Modo:</span><span id="iv-modo" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Bootloader:</span><span id="iv-grub" class="info-val">—</span></div>
        <div class="info-row"><span class="info-key">Usuario:</span><span id="iv-user" class="info-val ok">—</span></div>
        <div class="info-row"><span class="info-key">DE/WM:</span><span class="info-val ok">Hyprland · Wayland</span></div>
      </div>
      <div class="ph-section">▸ Progreso</div>
      <div id="steps-panel"></div>
      <div id="btn-area">
        <button class="action-btn" id="btn-abort" onclick="abortar()" data-i18n="btn-abort">⛔ Abortar</button>
        <button class="action-btn" id="btn-retry" onclick="reintentar()" data-i18n="btn-retry">↺ Reintentar</button>
      </div>
    </div>

    <div id="inst-right">
      <div id="log-header">
        <span id="log-title" data-i18n="log-title">▸ Log de instalación</span>
        <span id="log-lines-count">0 líneas</span>
      </div>
      <div id="log-wrap"><pre id="log"></pre></div>
      <div id="progress-bar-wrap"><div id="progress-bar"></div></div>
      <div id="statusbar">
        <span id="statusbar-msg">Esperando inicio…</span>
        <span id="statusbar-time"></span>
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: COUNTDOWN
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-countdown" class="overlay">
  <div class="box">
    <div id="cd-title" data-i18n="cd-title">⚠ ZONA DE NO RETORNO</div>
    <div id="cd-body"><span data-i18n="cd-about-to-erase">A punto de borrar</span> <span id="cd-dev" style="color:var(--ph-red);font-weight:700;"></span><br>
    <span id="cd-info" style="color:var(--ph-yellow);"></span><br>
    <span data-i18n="cd-data-permanent">Todos los datos serán eliminados permanentemente.</span></div>
    <div id="cd-num">10</div>
    <div id="cd-hint"><span data-i18n="cd-press">Pulsa</span> <kbd data-i18n="btn-abort" style="color:var(--ph-cyan);">⛔ Abortar</kbd> <span data-i18n="cd-to-cancel">para cancelar</span></div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: ELEGIR MIRROR (preflight de paquetes fallo tras reintentos)
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-mirror" class="overlay">
  <div class="box">
    <div id="mirror-title" data-i18n="mirror-title">⚠ Problema con el mirror de paquetes</div>
    <div id="mirror-body" data-i18n="mirror-body">Algunos paquetes no se pudieron resolver tras varios intentos — probablemente el mirror actual está atrasado o incompleto, no que el paquete no exista.</div>
    <div id="mirror-detalle"></div>
    <div class="mirror-btns">
      <button id="btn-mirror-aceptar" onclick="elegirMirror('aceptar')" data-i18n="btn-mirror-aceptar">Cambiar de mirror</button>
      <button id="btn-mirror-rechazar" onclick="elegirMirror('rechazar')" data-i18n="btn-mirror-rechazar">Lo hago yo</button>
      <button id="btn-mirror-reintentar" onclick="elegirMirror('reintentar')" data-i18n="btn-mirror-reintentar">Reintentar igual</button>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: ERROR FATAL
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-error" class="overlay">
  <div class="box">
    <div id="err-title" data-i18n="err-title">⛔ Error crítico</div>
    <div id="err-msg"></div>
    <div id="err-hint">Cierra esta ventana o presiona <kbd>Ctrl+C</kbd> en terminal</div>
    <button id="btn-err-close" onclick="window.pywebview.api.close()" data-i18n="btn-close">Cerrar</button>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════
     OVERLAY: DONE (instalación completada)
═══════════════════════════════════════════════════════════════════ -->
<div id="ov-done" class="overlay">
  <div class="box">
    <div id="done-icon">✓</div>
    <div id="done-title" data-i18n="done-title">AvalOS instalado correctamente</div>
    <div id="done-sub" data-i18n="done-desc">Retira el USB y reinicia el equipo.<br>
      SDDM te pedirá iniciar sesión → selecciona <strong>Hyprland</strong>.</div>
    <div id="done-info"></div>
    <div class="done-btns">
      <button id="btn-reboot" onclick="window.pywebview.api.reboot_system()" data-i18n="btn-reboot">⟳ Reiniciar ahora</button>
      <button id="btn-view-log" onclick="verLog()" data-i18n="btn-view-log">📋 Ver log</button>
      <button id="btn-close-done" onclick="window.pywebview.api.close()" data-i18n="btn-close">Cerrar</button>
    </div>
  </div>
</div>

<!-- Botón flotante para volver a la pantalla de "instalación completada"
     después de haber elegido "Ver log" — normalmente oculto (ver CSS). -->
<button id="btn-back-to-done" onclick="volverADone()" data-i18n="btn-back-to-done">← Volver</button>

<script>
'use strict';

// ══════════════════════════════════════════════════════════════════
//  INTERNACIONALIZACIÓN (i18n)
//  STRINGS se inyecta en runtime desde translations.TRANSLATIONS
//  (ver _build_html). Para añadir/editar un idioma o clave, editar
//  translations.py — es la única fuente de verdad para los textos
//  del wizard y de fastfetch.
// ══════════════════════════════════════════════════════════════════
const STRINGS = STRINGS_PLACEHOLDER;

let _lang = 'en';

// MOVIDO: PASOS vivía como `const` mucho más abajo (sección INSTALL PAGE).
// applyLang() lo lee vía "typeof PASOS" y se llama desde chooseLang() —
// osea, en CADA click/tecla de idioma. Cualquier excepción sin capturar
// entre el inicio del script y la línea vieja de PASOS (ej. alguna de las
// IIFEs initTZ/initLocale/initKeymap tirando por lo que sea en el entorno
// real) dejaba PASOS atascado en su temporal dead zone para siempre. A
// partir de ahí, TODO click o tecla repetía el mismo ReferenceError
// "Cannot access 'PASOS' before initialization" a medio camino de
// chooseLang() — antes de llegar a showPage() — y visualmente parecía que
// el click "no hacía nada". Declarándolo aquí arriba, antes de cualquier
// IIFE que pueda fallar, se lo saca por completo de esa cadena de fallos.
const PASOS = [
  { id:'uefi',     label:'Detectando modo de arranque',        detail:'UEFI / BIOS Legacy' },
  { id:'net',      label:'Verificando conexión a internet',    detail:'Requerida para pacstrap' },
  { id:'tools',    label:'Verificando herramientas',           detail:'parted, mkfs, pacstrap…' },
  { id:'part',     label:'Particionando disco destino',        detail:'' },
  { id:'format',   label:'Formateando particiones',            detail:'FAT32 (EFI) + Btrfs (root)' },
  { id:'mount',    label:'Montando sistema de archivos',       detail:'' },
  { id:'mirrors',  label:'Optimizando mirrors con reflector',  detail:'Seleccionando mirrors más rápidos' },
  { id:'pacstrap', label:'Instalando sistema base',            detail:'pacstrap — puede tardar varios minutos' },
  { id:'fstab',    label:'Generando fstab',                    detail:'' },
  { id:'config',   label:'Configurando sistema',               detail:'locale · hostname · timezone · initramfs' },
  { id:'grub',     label:'Instalando bootloader',               detail:'' },
  { id:'services', label:'Habilitando servicios',              detail:'NetworkManager · bluetooth · SDDM' },
  { id:'user',     label:'Creando usuario del sistema',        detail:'' },
  { id:'aur',      label:'Instalando paquetes AUR (yay)',      detail:'Proton-GE · Heroic (solo si Gaming activo)' },
  { id:'hypr', label:'Configurando Hyprland + Wayland',    detail:'SDDM · Waybar · hyprland.lua' },
  { id:'umount',   label:'Desmontando y finalizando',          detail:'' },
];

function t(key, params) {
  // BUG-FIX: no usar || para encadenar fallbacks — en JS, "" es falsy, así que
  // (dict[key] || fallback) devolvería 'key' en lugar de "" para las claves
  // step-*-d con detail vacío intencional. Esto corrompía PASOS en applyLang()
  // (s.detail = "step-part-d") y al hacer Retry se renderizaba la clave cruda en la UI.
  // Fix: comprobar explícitamente si la clave existe en el dict antes de recurrir al fallback.
  const dict = STRINGS[_lang] || STRINGS.en;
  let val = (key in dict) ? dict[key] : ((key in STRINGS.en) ? STRINGS.en[key] : key);
  // Sustitución simple de {nombre} -> valor, espejo de self._t(**kwargs) en Python,
  // para los pocos casos donde el texto traducido necesita un valor dinámico
  // (ej. el contador de líneas del log).
  if (params) {
    for (const k in params) val = val.split('{' + k + '}').join(params[k]);
  }
  return val;
}

function applyLang(code) {
  _lang = code;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    if (val) el.innerHTML = val;
  });
  // FIX: algunos elementos no traducen su contenido sino el atributo title
  // (ej. el botón 👁 mostrar/ocultar contraseña) — data-i18n ya cubre
  // innerHTML, pero title necesita su propio paso porque no es contenido visible.
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.dataset.i18nTitle;
    const val = t(key);
    if (val) el.title = val;
  });
  // BUG-i18n FIX: actualizar PASOS array Y nodos del DOM ya renderizados.
  // initSteps() se ejecuta en pywebviewready (antes de seleccionar idioma),
  // por lo que el DOM inicial queda en español. applyLang() actualizaba el
  // array PASOS pero no los elementos step-label / step-detail del DOM,
  // ya que no tienen data-i18n y se renderizan desde PASOS directamente.
  // Fix: también actualizar los nodos del DOM si el paso ya está renderizado.
  if (typeof PASOS !== 'undefined') {
    PASOS.forEach(s => {
      const lbl = t('step-' + s.id);
      const det = t('step-' + s.id + '-d');
      if (lbl !== undefined) s.label = lbl;
      if (det !== undefined) s.detail = det;
      // Actualizar DOM si el step ya está renderizado
      const stepEl = document.getElementById('step-' + s.id);
      if (stepEl) {
        const lblEl = stepEl.querySelector('.step-label');
        const detEl = stepEl.querySelector('.step-detail');
        // BUG-12 FIX: "if (lblEl && lbl)" / "if (detEl && det)" usaban chequeo
        // truthy — el mismo problema que t() ya resuelve explícitamente (una
        // traducción vacía "" es válida y no debe tratarse como "no hay
        // traducción"). Con detail = "" en algún idioma y no vacío en otro,
        // el texto viejo se quedaba pegado en el DOM al cambiar de idioma.
        // Misma condición que ya se usa 2 líneas arriba para s.detail.
        if (lblEl && lbl !== undefined) lblEl.textContent = lbl;
        if (detEl && det !== undefined) detEl.textContent = det;
      }
    });
  }
  document.title = t('title');
  const llc = document.getElementById('log-lines-count');
  if (llc) llc.textContent = t('log-lines-count', { n: logLines });
  // BUG-i18n FIX: las tarjetas de disco (pyRenderDiscos) se arman con
  // innerHTML compuesto por t() en el momento de creación, no con
  // data-i18n — mismo problema estructural que PASOS arriba, mismo tipo
  // de solución: si ya se listaron discos, volver a renderizarlos con el
  // idioma nuevo. pyRenderDiscos() ya preserva cuál estaba seleccionado.
  if (_ultimoDiscosJson) {
    pyRenderDiscos(_ultimoDiscosJson);
  }
}

function chooseLang(code) {
  applyLang(code);
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_language(code);
  }
  showPage('welcome');
}

// REFUERZO: el keydown se registra ANTES que el delegado de click, a
// propósito — document.addEventListener('keydown', ...) nunca puede fallar
// (document siempre existe), a diferencia de getElementById('pg-lang') de
// abajo. Poniéndolo primero, el atajo de teclado queda registrado pase lo
// que pase con la línea siguiente.
document.addEventListener('keydown', function (e) {
  const pgLang = document.getElementById('pg-lang');
  if (!pgLang || !pgLang.classList.contains('active')) return;

  const langBtns = Array.from(pgLang.querySelectorAll('button[data-lang]'));
  const byKeyNumber = { '1': 'en', '2': 'es', '3': 'zh', '4': 'ja' };

  if (byKeyNumber[e.key]) {
    chooseLang(byKeyNumber[e.key]);
    return;
  }

  if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
    const focused = document.activeElement;
    if (langBtns.includes(focused)) {
      e.preventDefault();
      chooseLang(focused.dataset.lang);
    }
    return;
  }

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const focusedIdx = langBtns.indexOf(document.activeElement);
    const delta = e.key === 'ArrowDown' ? 1 : -1;
    const nextIdx = focusedIdx === -1
      ? 0
      : (focusedIdx + delta + langBtns.length) % langBtns.length;
    langBtns[nextIdx].focus();
  }
});

// REFUERZO: delegado de click sobre el contenedor de idioma. Envuelto en
// try/catch — si getElementById('pg-lang') fallara por lo que sea, no debe
// tumbar el resto del script (el keydown de arriba y todo lo que sigue
// abajo, como las IIFEs de timezone/locale/keymap, deben seguir corriendo).
try {
  document.getElementById('pg-lang').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-lang]');
    if (btn) chooseLang(btn.dataset.lang);
  });
} catch (err) {
  console.error('lang click delegate:', err);
  if (window.__showJsError) window.__showJsError('lang click delegate: ' + err.message);
}

// ══════════════════════════════════════════════════════════════════
//  NAVIGATION
// ══════════════════════════════════════════════════════════════════
// showPage() controla visibilidad SOLO vía la clase 'active' (ver CSS
// .page/.page.active). No asignes el.style.display aquí ni en el HTML de
// ninguna .page — un inline style gana a la cascada y la página queda
// visualmente encima aunque pierda 'active'.
function showPage(name) {
  ['lang','welcome','config','install'].forEach(p => {
    const el = document.getElementById('pg-' + p);
    if (!el) {
      console.error('showPage: no existe #pg-' + p);
      if (window.__showJsError) window.__showJsError('showPage: falta #pg-' + p);
      return;
    }
    el.classList.toggle('active', p === name);
  });
}

// ══════════════════════════════════════════════════════════════════
//  WIZARD CONFIG STATE
// ══════════════════════════════════════════════════════════════════
let _selDisco = '';
let _bootloader = 'grub';  // 'grub' | 'sd-boot' | 'refind' | 'none'
let _modoUsb  = false;

// populate timezone select
try {
  (function initTZ() {
    const sel = document.getElementById('f-tz');
    window._tzList.forEach(tz => {
      const opt = document.createElement('option');
      opt.value = tz; opt.textContent = tz;
      if (tz === window._defaultTZ) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initTZ:', err);
  if (window.__showJsError) window.__showJsError('initTZ: ' + err.message);
}

// populate locale select
try {
  (function initLocale() {
    const sel = document.getElementById('f-locale');
    window._localeList.forEach(([code, label]) => {
      const opt = document.createElement('option');
      opt.value = code; opt.textContent = label;
      if (code === window._defaultLocale) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initLocale:', err);
  if (window.__showJsError) window.__showJsError('initLocale: ' + err.message);
}

// populate keymap select
try {
  (function initKeymap() {
    const sel = document.getElementById('f-keymap');
    window._keymapList.forEach(([code, label]) => {
      const opt = document.createElement('option');
      opt.value = code; opt.textContent = label;
      if (code === window._defaultKeymap) opt.selected = true;
      sel.appendChild(opt);
    });
  })();
} catch (err) {
  console.error('initKeymap:', err);
  if (window.__showJsError) window.__showJsError('initKeymap: ' + err.message);
}

// ── Disk selection ────────────────────────────────────────────────
// BUG-i18n: pyRenderDiscos() se invoca UNA sola vez desde Python al
// listar discos (InstallerAPI.on_ready), así que las
// tarjetas de disco (incluyendo tag-disco-actual-live y tag-montado, que
// se inyectan vía t() en el momento de creación) quedaban congeladas en
// el idioma que estaba activo en ese instante. Si el usuario cambiaba de
// idioma DESPUÉS de que la lista ya cargó, las tarjetas nunca se
// actualizaban porque no tienen data-i18n (son innerHTML compuesto, no
// un solo nodo de texto) y applyLang() nunca volvía a llamar a
// pyRenderDiscos(). Fix: cachear el último JSON recibido para poder
// re-renderizar la lista completa desde applyLang() sin pedirle los
// datos de nuevo a Python.
let _ultimoDiscosJson = null;

function pyRenderDiscos(discosJson) {
  _ultimoDiscosJson = discosJson;
  const _seleccionPrevia = _selDisco;
  const discos = JSON.parse(discosJson);
  const cont = document.getElementById('disk-list');
  cont.innerHTML = '';
  let autoSel = '';
  discos.forEach(d => {
    const esBoot = d.es_arranque;
    const sizeGb = (d.size_b / 1e9).toFixed(1);
    const bajo   = parseFloat(sizeGb) < 30;
    // FIX: la condición anterior "!d.tran.includes('SATA') && d.tipo === 'SSD/NVMe'"
    // marcaba como 'nvme' a CUALQUIER disco no-rotacional cuyo transporte no fuera
    // SATA (ej. un SSD externo por USB, o un disco virtio en una VM), aunque no
    // fuera NVMe real. Ahora 'nvme' solo se asigna si el transporte es NVMe o el
    // nombre del dispositivo lo indica (ej. "nvme0n1") — igual que detectar_tipo_disco_destino()
    // en el lado Python. Cualquier otro disco no-rotacional cae en 'ssd'.
    const esNvme = d.tran === 'NVME' || d.name.includes('nvme');
    const tipo   = esNvme ? 'nvme' :
                   d.tipo === 'SSD/NVMe' ? 'ssd' : 'hdd';

    if (!esBoot && !autoSel) autoSel = d.name;

    const div = document.createElement('div');
    div.className = 'disk-card' + (esBoot ? ' boot-disk' : '');
    div.id = 'dc-' + d.name;
    div.innerHTML = `
      <div class="disk-name">
        /dev/${d.name}
        <span class="dtag dtag-${tipo}">${d.tipo}</span>
        ${esBoot ? `<span class="dtag dtag-boot">${t('tag-disco-actual-live')}</span>` : ''}
      </div>
      <div class="disk-meta">
        <span class="disk-size">${d.size_human}</span> · ${d.model} · ${d.tran}
        ${d.montajes.length ? ` · <span style="color:var(--tn-orange)">${t('tag-montado')}</span>` : ''}
      </div>
      ${esBoot ? '<div class="disk-warn" style="color:var(--tn-dim);font-style:italic;">No disponible: es el disco donde corre este live ISO</div>' : ''}
      ${bajo && !esBoot ? `<div class="disk-warn">⚠ Solo ${sizeGb} GB — se recomiendan ≥30 GB</div>` : ''}
    `;
    if (!esBoot) div.onclick = () => selectDisk(d.name);
    cont.appendChild(div);
  });
  // Preservar la selección del usuario si ya había una y sigue existiendo
  // en la nueva lista (ej. re-render por cambio de idioma) — solo caer a
  // auto-selección la primera vez que se lista, cuando no había nada elegido.
  const _sigueExistiendo = _seleccionPrevia && discos.some(d => d.name === _seleccionPrevia);
  if (_sigueExistiendo) {
    selectDisk(_seleccionPrevia);
  } else if (autoSel) {
    selectDisk(autoSel);
  }
  // Show banner only if there's a boot disk in the list
  const hasBoot = discos.some(d => d.es_arranque);
  const banner = document.getElementById('live-disk-banner');
  if (banner) banner.style.display = hasBoot ? 'block' : 'none';
}

function selectDisk(name) {
  _selDisco = name;
  // Auto-suggest USB mode when the selected disk has USB transport
  try {
    const dc = document.getElementById('dc-' + name);
    const meta = dc ? dc.querySelector('.disk-meta') : null;
    const metaTxt = meta ? meta.textContent.toLowerCase() : '';
    // BUG-FIX: name.startsWith('sd') marcaba como USB cualquier disco SATA
    // interno (sda, sdb... también son SATA, no solo USB), activando el modo
    // "USB Persistente" (ext4 sin journal) en instalaciones normales sobre un
    // SSD/HDD SATA interno en lugar del modo PC/Btrfs correcto. metaTxt ya
    // incluye d.tran (el transporte real reportado por lsblk: "usb"/"sata"/
    // "nvme"), que es la señal correcta — sin heurística de nombre de archivo.
    const isUsb = metaTxt.includes('usb');
    // Only auto-switch if user hasn't manually picked
    if (isUsb && !window._modoManuallySet) {
      selModo('usb');
    }
  } catch(e) {}
  document.querySelectorAll('.disk-card').forEach(c => {
    const isSel = c.id === 'dc-' + name;
    c.classList.toggle('selected', isSel);
    // remove/add DESTINO tag
    let tag = c.querySelector('.dtag-sel');
    if (isSel && !tag) {
      tag = document.createElement('span');
      tag.className = 'dtag dtag-sel'; tag.setAttribute('data-i18n', 'tag-destino');
      tag.textContent = t('tag-destino');
      c.querySelector('.disk-name').appendChild(tag);
    } else if (!isSel && tag) {
      tag.remove();
    }
  });
}

// ── Modo manual (particionado a mano en terminal real) ─────────────
// El terminal NO corre dentro del webview (webkit2gtk no tiene uno
// embebido) — Python lanza un emulador real del sistema y bloquea hasta
// que el usuario lo cierra. Por eso este botón se deshabilita mientras
// tanto: evita doble-click y dos terminales superpuestas.
async function abrirModoManual() {
  if (!_selDisco) {
    showFormError(t('val-select-disk'));
    return;
  }
  const btn = document.getElementById('btn-manual-mode');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = t('btn-manual-mode-open');
  document.getElementById('manual-root-picker').style.display = 'none';
  try {
    const abierto = await window.pywebview.api.open_partitioning_terminal();
    if (!abierto) {
      showFormError(t('err-no-terminal-found'));
      return;
    }
    const resultado = await window.pywebview.api.check_manual_partitioning(_selDisco);
    aplicarResultadoParticionadoManual(resultado);
  } catch (e) {
    console.error('abrirModoManual:', e);
    if (window.__showJsError) window.__showJsError('abrirModoManual: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// Separado de abrirModoManual() para poder reusarlo si en el futuro se
// agrega un botón "re-verificar" sin tener que reabrir la terminal.
function aplicarResultadoParticionadoManual(resultado) {
  if (!resultado || !resultado.ok) {
    window._modoManualListo = false;
    showFormError(t('warn-manual-no-partitions'));
    return;
  }

  if (resultado.requiere_seleccion) {
    // Más de una candidata a root — no se puede continuar todavía, el
    // usuario tiene que elegir en el dropdown (confirmarRootManual()).
    window._modoManualListo = false;
    poblarDropdownRootManual(resultado.candidatas_root);
    document.getElementById('manual-root-picker').style.display = 'flex';
    return;
  }

  // Candidata única — Python ya la fijó como root en
  // verificar_particionado_manual(), acá solo reflejamos el estado.
  window._modoManualListo = true;
  document.getElementById('manual-root-picker').style.display = 'none';
  showFormError(t('ok-manual-partition-detected'));
}

function poblarDropdownRootManual(candidatas) {
  const sel = document.getElementById('manual-root-select');
  sel.innerHTML = '';
  candidatas.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = `${c.name} — ${c.size_human} — ${c.fstype}`;
    sel.appendChild(opt);
  });
}

async function confirmarRootManual() {
  const sel = document.getElementById('manual-root-select');
  const elegida = sel.value;
  if (!elegida) return;
  const btn = document.getElementById('btn-confirm-manual-root');
  btn.disabled = true;
  try {
    const ok = await window.pywebview.api.confirm_manual_root(_selDisco, elegida);
    if (ok) {
      window._modoManualListo = true;
      document.getElementById('manual-root-picker').style.display = 'none';
      showFormError(t('ok-manual-partition-detected'));
    } else {
      window._modoManualListo = false;
      showFormError(t('err-manual-invalid-root-choice'));
    }
  } catch (e) {
    console.error('confirmarRootManual:', e);
    if (window.__showJsError) window.__showJsError('confirmarRootManual: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── Form helpers ─────────────────────────────────────────────────
function sanitizeUser(el) {
  el.value = el.value.toLowerCase()
    .replace(/[^a-z0-9_-]/g, '')
    .replace(/^[-]+/, '');  // BUG-008: '-hola' como argumento en useradd puede interpretarse como flag
  const h = document.getElementById('hint-user');
  const startsWithLetter = /^[a-z_]/.test(el.value);
  const validLen = el.value.length >= 2 && el.value.length <= 32;
  const ok = validLen && startsWithLetter;
  let hint = t('val-invalid-user');
  if (el.value) {
    if (!startsWithLetter) hint = t('val-invalid-user');
    else if (!validLen)     hint = t('val-min-user');
    else                    hint = '✓';
  }
  h.className = 'field-hint ' + (el.value ? (ok ? 'good' : 'err') : '');
  h.textContent = hint;
  el.className = el.value ? (ok ? 'ok' : 'error') : '';
}

function sanitizeHost(el) {
  el.value = el.value.toLowerCase().replace(/[^a-z0-9-]/g, '').replace(/^-+/, '');
}

// ── Password toggle (show/hide) ───────────────────────────────────
function togglePass(inputId, btnId) {
  const inp = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  if (inp.type === 'password') {
    inp.type = 'text';
    btn.style.opacity = '1';
    btn.textContent = '🙈';
  } else {
    inp.type = 'password';
    btn.style.opacity = '0.45';
    btn.textContent = '👁';
  }
}

// ── Password strength checker ─────────────────────────────────────
function _passStrength(p) {
  const checks = {
    len:   p.length >= 8,
    upper: /[A-Z]/.test(p),
    lower: /[a-z]/.test(p),
    num:   /[0-9]/.test(p),
    sym:   /[^A-Za-z0-9]/.test(p),
  };
  const score = Object.values(checks).filter(Boolean).length;
  return { checks, score };
}

function checkPass() {
  const p1 = document.getElementById('f-pass').value;
  const p2 = document.getElementById('f-pass2').value;
  const h  = document.getElementById('hint-pass');
  const bar = document.getElementById('strength-bar');

  // -- strength requirements (left field)
  if (p1) {
    const { checks, score } = _passStrength(p1);
    // update req indicators
    const map = { len: 'req-len', upper: 'req-upper', lower: 'req-lower', num: 'req-num', sym: 'req-sym' };
    const labels  = { len: t('req-len-ok'), upper: t('req-upper-ok'), lower: t('req-lower-ok'), num: t('req-num-ok'), sym: t('req-sym-ok') };
    const labelsX = { len: t('req-len-x'),  upper: t('req-upper-x'),  lower: t('req-lower-x'),  num: t('req-num-x'),  sym: t('req-sym-x')  };
    Object.entries(map).forEach(([k, id]) => {
      const el = document.getElementById(id);
      el.className = 'req' + (checks[k] ? ' ok' : '');
      el.textContent = checks[k] ? labels[k] : labelsX[k];
    });
    // update bar
    bar.className = 'strength-bar s' + score;
    // update left input border
    const inp1 = document.getElementById('f-pass');
    inp1.className = score >= 3 ? 'ok' : 'error';
  } else {
    bar.className = 'strength-bar s0';
    ['req-len','req-upper','req-lower','req-num','req-sym'].forEach(id => {
      const el = document.getElementById(id);
      el.className = 'req';
    });
    document.getElementById('f-pass').className = '';
  }

  // -- confirm match (right field)
  if (!p1) { h.textContent = ''; h.className = 'field-hint'; document.getElementById('f-pass2').className = ''; return; }
  if (!p2)  { h.textContent = ''; h.className = 'field-hint'; document.getElementById('f-pass2').className = ''; return; }
  if (p1 === p2) {
    h.textContent = t('val-pass-ok');
    h.className = 'field-hint good';
    document.getElementById('f-pass2').className = 'ok';
  } else {
    h.textContent = t('val-pass-mismatch');
    h.className = 'field-hint err';
    document.getElementById('f-pass2').className = 'error';
  }
}

function selBootloader(val) {
  _bootloader = val;
  const map = {grub:'opt-bl-grub','sd-boot':'opt-bl-sd','refind':'opt-bl-refind','none':'opt-bl-none'};
  Object.entries(map).forEach(([k,id]) => {
    document.getElementById(id).classList.toggle('sel', k === val);
  });

  // ── Advertencia de snapshots para non-GRUB ──────────────────────────────
  const snapWarn = document.getElementById('snap-boot-warning');
  if (snapWarn) {
    if (val === 'sd-boot') {
      snapWarn.style.display = 'block';
      snapWarn.innerHTML = t('warn-sdboot-snaps');
    } else if (val === 'refind') {
      snapWarn.style.display = 'block';
      snapWarn.innerHTML = t('warn-refind-snaps');
    } else {
      snapWarn.style.display = 'none';
    }
  }

  // Advertencia UEFI requerido para sd-boot y rEFInd
  if (val === 'refind' || val === 'sd-boot') {
    const name = val === 'refind' ? 'rEFInd' : 'systemd-boot';
    if (window._esUEFI === false) {
      showFormError('⛔ ' + name + ' ' + t('val-uefi-req'));
    } else if (window._esUEFI === undefined) {
      showFormError('⚠ ' + name + ' ' + t('val-uefi-warn'));
    }
  }
}

function selModo(val, manual) {
  if (manual) window._modoManuallySet = true;
  _modoUsb = (val === 'usb');
  document.getElementById('opt-modo-disco').classList.toggle('sel', !_modoUsb);
  document.getElementById('opt-modo-usb').classList.toggle('sel', _modoUsb);
}

function showFormError(msg) {
  const el = document.getElementById('form-error');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

function validarEIniciar() {
  const user   = document.getElementById('f-user').value.trim();
  const pass   = document.getElementById('f-pass').value;
  const pass2  = document.getElementById('f-pass2').value;
  const host   = document.getElementById('f-host').value.trim() || window._defaultHostname;
  const tz     = document.getElementById('f-tz').value;
  const locale = document.getElementById('f-locale').value;
  const keymap = document.getElementById('f-keymap').value;

  if (!_selDisco)                   return showFormError(t('val-select-disk'));
  if (!user || user.length < 2)     return showFormError(t('val-invalid-user'));
  if (pass.length < 8)              return showFormError(t('val-pass-short'));
  if (_passStrength(pass).score < 2) return showFormError(t('val-pass-weak'));
  if (pass !== pass2)               return showFormError(t('val-pass-mismatch'));
  // FIX: lista ampliada con usernames de sistema reales en Arch/systemd
  // (la original solo tenía 5; hay decenas de usernames reservados por paquetes)
  const _RESERVED = [
    'root','daemon','bin','sys','sync','games','man','lp','mail','news',
    'uucp','proxy','backup','list','irc','nobody',
    // Arch / systemd específicos
    'http','ftp','git','sshd','dbus','polkitd','avahi','colord','rtkit',
    'uuidd','nm-openconnect','ntp','systemd-network','systemd-resolve',
    'systemd-timesync','tss','messagebus','cups','gdm','lightdm','sddm',
    'mysql','postgres','redis','mongodb','www','nobody','operator',
  ];
  if (_RESERVED.includes(user))
                                    return showFormError(t('val-reserved-user'));

  // Pasar a la página de instalación y avisar a Python
  showPage('install');
  const _gaming = window._installGaming === true;
  const _bore   = window._installBore === true;
  const _manual = window._modoManualListo === true;
  window.pywebview.api.start_installation(user, pass, host, tz, _selDisco, _bootloader, _modoUsb, locale, keymap, _gaming, _bore, _manual);
}

// ══════════════════════════════════════════════════════════════════
//  INSTALL PAGE
// ══════════════════════════════════════════════════════════════════
let logLines = 0, startTime = null, timerIv = null, abortado = false;

function initSteps() {
  const cont = document.getElementById('steps-panel');
  cont.innerHTML = '';
  PASOS.forEach(p => {
    const d = document.createElement('div');
    d.className = 'step'; d.id = 'step-' + p.id;
    d.innerHTML = `<span class="step-icon">○</span><div>
      <div class="step-label">${p.label}</div>
      ${p.detail ? `<div class="step-detail">${p.detail}</div>` : ''}
    </div>`;
    cont.appendChild(d);
  });
}

function setStep(id, estado, detalle) {
  const el = document.getElementById('step-' + id);
  if (!el) return;
  el.className = 'step ' + estado;
  const icons = { done:'✓', active:'▶', error:'✗', skip:'—' };
  el.querySelector('.step-icon').textContent = icons[estado] || '○';
  if (detalle) {
    let dd = el.querySelector('.step-detail');
    if (!dd) { dd = document.createElement('div'); dd.className = 'step-detail'; el.firstElementChild.appendChild(dd); }
    dd.textContent = detalle;
  }
  if (estado === 'active') el.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function setProgress(pct) {
  document.getElementById('progress-bar').style.width = Math.min(100, pct) + '%';
}

function appendLog(texto, clase) {
  const pre = document.getElementById('log');
  const span = document.createElement('span');
  if (clase) span.className = 'log-' + clase;
  span.textContent = texto + '\n';
  pre.appendChild(span);
  logLines++;
  document.getElementById('log-lines-count').textContent = t('log-lines-count', { n: logLines });
  const wrap = document.getElementById('log-wrap');
  wrap.scrollTop = wrap.scrollHeight;
}

function setInfo(id, val, cls) {
  const el = document.getElementById('iv-' + id);
  if (!el) return;
  el.textContent = val;
  el.className = 'info-val ' + (cls || '');
}

function setStatus(msg) { document.getElementById('statusbar-msg').textContent = msg; }

function startTimer() {
  startTime = Date.now();
  timerIv = setInterval(() => {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    document.getElementById('statusbar-time').textContent =
      (m > 0 ? m + 'm ' : '') + (s % 60) + 's';
  }, 1000);
}
function stopTimer() { if (timerIv) clearInterval(timerIv); }

// ── Buttons ───────────────────────────────────────────────────────
function abortar() {
  if (abortado) return;
  abortado = true;
  document.getElementById('btn-abort').disabled = true;
  appendLog('\n[USUARIO] Instalación abortada.', 'err');
  setStatus('Abortado — limpiando montajes…');
  window.pywebview.api.abort_installation();
}
function reintentar() {
  document.getElementById('btn-retry').style.display = 'none';
  document.getElementById('btn-abort').disabled = false;
  abortado = false;
  window.pywebview.api.retry();
}

// ══════════════════════════════════════════════════════════════════
//  PYTHON → JS  callbacks
// ══════════════════════════════════════════════════════════════════
function pyLog(texto, clase)     { appendLog(texto, clase || 'info'); }
function pyStep(id, estado, det) { setStep(id, estado, det || ''); }
function pyProgress(pct)         { setProgress(pct); }
function pyInfo(id, val, cls)    { setInfo(id, val, cls || ''); }
function pyStatus(msg)           { setStatus(msg); }
function pyStartTimer()          { startTimer(); }
function pyStopTimer()           { stopTimer(); }
function pyStatusLabel(txt)      { document.getElementById('status-label').textContent = txt; }

function pyBadges(internet, uefi) {
  window._esUEFI = uefi;
  const nb = document.getElementById('internet-badge');
  if (internet === null || internet === undefined) {
    nb.textContent = 'NET ···';
    nb.className   = 'badge-warn';
    setInfo('net', t('badge-checking'), 'warn');
  } else {
    nb.textContent = internet ? 'NET ✓' : t('badge-no-network');
    nb.className   = 'badge-' + (internet ? 'ok' : 'err');
    setInfo('net', internet ? t('step-net-up') : t('step-net-down'), internet ? 'ok' : 'err');
  }
  const ub = document.getElementById('uefi-badge');
  ub.textContent = uefi ? 'UEFI' : 'BIOS';
  setInfo('boot', uefi ? 'UEFI (GPT)' : 'BIOS Legacy (MBR)', 'ok');
}

function pyIniciarCountdown(dev, modelo, size) {
  document.getElementById('cd-dev').textContent = dev;
  document.getElementById('cd-info').textContent = modelo + ' · ' + size;
  const el = document.getElementById('cd-num');
  if (el) el.textContent = 10;
  document.getElementById('ov-countdown').classList.add('show');
  // BUG-009 FIX: el countdown ya no corre de forma independiente con setInterval.
  // Python controla el tiempo real y llama pyActualizarCountdown() en cada tick,
  // garantizando que la acción destructiva no ocurre antes de que el contador llegue a 0.
}

function pyActualizarCountdown(n) {
  const el = document.getElementById('cd-num');
  if (el) el.textContent = n;
}

function pyCerrarCountdown() {
  const ov = document.getElementById('ov-countdown');
  ov.classList.remove('show');
}

function pyInstalacionCompleta(info) {
  stopTimer();
  document.getElementById('btn-abort').disabled = true;
  document.getElementById('status-label').textContent = '✓ completado';
  setProgress(100);
  setStatus('Instalación completada — reinicia el equipo');
  // Show done overlay
  if (info) document.getElementById('done-info').innerHTML = info;
  document.getElementById('ov-done').classList.add('show');
}

// "Ver log": esconde el overlay de done (el log siempre estuvo detrás,
// nunca se destruye, ver #log-wrap más arriba) y muestra el botón
// flotante para volver. No llama a close() en ningún momento -- a
// diferencia del botón "Cerrar", esto no termina el proceso.
function verLog() {
  document.getElementById('ov-done').classList.remove('show');
  document.getElementById('btn-back-to-done').classList.add('show');
}

function volverADone() {
  document.getElementById('btn-back-to-done').classList.remove('show');
  document.getElementById('ov-done').classList.add('show');
}


function pyMirrorDialog(detalle) {
  document.getElementById('mirror-detalle').textContent = detalle || '';
  document.getElementById('ov-mirror').classList.add('show');
}

function elegirMirror(choice) {
  document.getElementById('ov-mirror').classList.remove('show');
  window.pywebview.api.choose_mirror(choice);
}

function pyErrorFatal(msg) {
  stopTimer();
  document.getElementById('btn-abort').disabled = true;
  document.getElementById('btn-retry').style.display = 'block';
  document.getElementById('err-msg').textContent = msg;
  document.getElementById('ov-error').classList.add('show');
}

function pyErrorPaso(msg) {
  stopTimer();
  document.getElementById('btn-retry').style.display = 'block';
  appendLog('\n[ERROR] ' + msg, 'err');
  setStatus(t('status-error'));
  document.getElementById('status-label').textContent = '✗ error';
}

// ══════════════════════════════════════════════════════════════════
//  READY
// ══════════════════════════════════════════════════════════════════
window.addEventListener('pywebviewready', function() {
  initSteps();
  window.pywebview.api.on_ready();
});
</script>
</body>
</html>
"""

def build_html() -> str:
    """Arma el HTML final del wizard: inyecta el logo (LOGO_PLACEHOLDER),
    las traducciones (STRINGS_PLACEHOLDER) y las listas de timezone/
    locale/keymap + sus defaults como variables globales de JS.

    El punto de inyección de estas últimas es ANTES de 'use strict' (no
    antes del listener de pywebviewready, como estaba en un diseño
    anterior) porque initTZ()/initLocale()/initKeymap() son IIFEs que se
    auto-ejecutan apenas se declaran, mucho antes de pywebviewready, y
    leen exactamente esas variables — con el punto de inyección viejo
    todavía no existían cuando esas IIFEs corrían, lo que rompía en
    silencio los 3 selectores del wizard en los 3 idiomas por igual."""
    tz_json = json.dumps(TIMEZONES, ensure_ascii=False)
    default_tz = json.dumps(DEFAULT_TIMEZONE)
    default_host = json.dumps(DEFAULT_HOSTNAME)
    locales_json = json.dumps(LOCALES, ensure_ascii=False)
    keymaps_json = json.dumps(KEYMAPS, ensure_ascii=False)
    default_loc = json.dumps(DEFAULT_LOCALE)
    default_km = json.dumps(DEFAULT_KEYMAP)

    strings_json = json.dumps(translations.TRANSLATIONS, ensure_ascii=False)

    inject = (
        f"window._tzList = {tz_json};\n"
        f"window._defaultTZ = {default_tz};\n"
        f"window._defaultHostname = {default_host};\n"
        f"window._localeList = {locales_json};\n"
        f"window._keymapList = {keymaps_json};\n"
        f"window._defaultLocale = {default_loc};\n"
        f"window._defaultKeymap = {default_km};\n"
    )

    content = _HTML.replace("LOGO_PLACEHOLDER", LOGO_B64)
    content = content.replace("STRINGS_PLACEHOLDER", strings_json)
    return content.replace(
        "'use strict';",
        "'use strict';\n" + inject
    )
