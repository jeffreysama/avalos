"""
╔══════════════════════════════════════════════════════════════════╗
║  AvalOS USB Maker  v2.0  (Windows · Ventoy edition)            ║
║  PyWebView · WebView2 · Fosfor verde                            ║
╚══════════════════════════════════════════════════════════════════╝

Prepara una USB booteable con Ventoy y copia el instalador GAIA.

  FASE 1 — En Windows (este .exe):
    1. Detecta USBs disponibles (≥8 GB recomendado)
    2. Descarga Ventoy si no está en la carpeta
    3. Instala Ventoy en la USB (partición EFI + partición data ExFAT)
    4. Copia el ISO de Arch Linux a la partición data
    5. Copia skill_instalar_usb.py + lanzar_avalos.sh a la partición data

  FASE 2 — En Arch Live (al bootear):
    • Ventoy muestra menú con el ISO — seleccionar Arch Linux
    • En la terminal del live:
        bash /run/mnt/ventoy/lanzar_avalos.sh
    • La GUI fosfor verde pide usuario, contraseña y hostname
    • Instala Arch + Hyprland + kernel AvalOS en el disco elegido

REQUISITOS WINDOWS:
  · Windows 10/11 con WebView2 (incluido en Win11, descarga automática en Win10)
  · Ejecutar como Administrador
  · skill_instalar_usb.py en la misma carpeta que este exe
  · ISO de Arch Linux (≥900 MB) — se puede seleccionar con el botón explorar

BUILD:
  pip install pyinstaller pywebview requests
  pyinstaller gaia_usb_maker.spec
  → dist/gaia_usb_maker.exe
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import urlretrieve, urlopen

import webview  # type: ignore

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

MIN_USB_GB       = 8            # AvalOS ISO pesa ~2 GB + espacio extra
VENTOY_VERSION   = "1.0.99"    # fallback — se detecta la última desde GitHub si hay red
VENTOY_API_URL   = "https://api.github.com/repos/ventoy/Ventoy/releases/latest"
VENTOY_FALLBACK  = f"https://github.com/ventoy/Ventoy/releases/download/v{VENTOY_VERSION}/ventoy-{VENTOY_VERSION}-windows.zip"
# El instalador gráfico va DENTRO del ISO (lo bundlea build-avalos-iso.sh).
# skill_instalar_usb.py se copia a la raíz del USB como respaldo, pero NO
# es necesario para el flujo automático — el wizard abre solo al bootear.
SCRIPT_NAME      = "skill_instalar_usb.py"
LAUNCHER_NAME    = "lanzar_avalos.sh"   # respaldo manual

LAUNCHER_SH = r"""#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════════╗
# ║  AvalOS — Lanzador manual (respaldo)                         ║
# ╠═══════════════════════════════════════════════════════════════╣
# ║  El instalador se abre AUTOMÁTICAMENTE al arrancar el live.  ║
# ║  Este script es un respaldo por si lo cierras y quieres      ║
# ║  volver a abrirlo desde la terminal (Super+Return → kitty).  ║
# ║                                                              ║
# ║  Uso:  bash /run/mnt/ventoy/lanzar_avalos.sh                ║
# ╚═══════════════════════════════════════════════════════════════╝
set -e
echo "══════════════════════════════════════════════════"
echo "  AvalOS Installer — lanzador manual"
echo "══════════════════════════════════════════════════"

# 1. Instalador dentro del ISO (ruta estándar del live)
INSTALLED="/usr/local/bin/avalos-install"
if [ -f "$INSTALLED" ]; then
    echo "[OK] Usando instalador del sistema: $INSTALLED"
    exec sudo python "$INSTALLED"
fi

# 2. Buscar skill_instalar_usb.py en la partición Ventoy (respaldo)
for SEARCH in /run/mnt/ventoy /mnt/ventoy /run/archiso/bootmnt; do
    if [ -f "$SEARCH/skill_instalar_usb.py" ]; then
        SCRIPT_PATH="$SEARCH/skill_instalar_usb.py"; break
    fi
done

if [ -z "${SCRIPT_PATH:-}" ]; then
    echo "[ERROR] Instalador no encontrado. Debería estar en /usr/local/bin/avalos-install"
    exit 1
fi

if ! python -c "import webview" 2>/dev/null; then
    echo "[INFO] Instalando pywebview..."
    pip install pywebview --break-system-packages --quiet
fi

echo "[OK] Lanzando AvalOS Installer..."
sudo python "$SCRIPT_PATH"
"""

# ══════════════════════════════════════════════════════════════════════════════
#  HTML — Estética fosfor verde
# ══════════════════════════════════════════════════════════════════════════════

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>AvalOS — USB Maker</title>
<style>
:root {
  --bg:        #020c02;
  --bg2:       #030f03;
  --bg3:       #061006;
  --border:    #0d2a0d;
  --green:     #39ff14;
  --gdim:      #1a9a08;
  --glo:       #082808;
  --amber:     #ffb300;
  --red:       #ff3b3b;
  --cyan:      #00f5d4;
  --text:      #c8e6c8;
  --muted:     #3a6a3a;
  --r:         4px;
  --f:         'Cascadia Code','Consolas','Courier New',monospace;
  --t:         .15s ease;
}
*{ box-sizing:border-box; margin:0; padding:0; }
html,body{ height:100%; background:var(--bg); color:var(--text);
  font-family:var(--f); font-size:12.5px; overflow:hidden; }
body::before{
  content:''; position:fixed; inset:0; pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,
    rgba(57,255,20,.012) 2px,rgba(57,255,20,.012) 4px);
  z-index:999;
}
::-webkit-scrollbar{ width:4px; }
::-webkit-scrollbar-thumb{ background:var(--glo); border-radius:2px; }

/* ── topbar ── */
#topbar{
  height:40px; background:var(--bg2);
  border-bottom:1px solid var(--border);
  display:flex; align-items:center; padding:0 14px; gap:10px; flex-shrink:0;
}
.logo{ color:var(--green); font-size:13px; font-weight:700;
  letter-spacing:2px; text-shadow:0 0 8px rgba(57,255,20,.5); }
.logo-sub{ color:var(--muted); font-size:10px; }
#topbar-right{ margin-left:auto; display:flex; gap:8px; align-items:center; }
.tbadge{
  font-size:10px; padding:2px 8px; border-radius:2px;
  border:1px solid var(--border); letter-spacing:.5px;
}
.tbadge.ok { color:var(--green); border-color:var(--glo); }
.tbadge.err{ color:var(--red);   border-color:#3a0808; }
.tbadge.dim{ color:var(--muted); }

/* ── layout ── */
#layout{ display:flex; height:calc(100vh - 64px); }

/* ── sidebar ── */
#sidebar{
  width:280px; min-width:240px; border-right:1px solid var(--border);
  display:flex; flex-direction:column; overflow:hidden;
}
.phead{
  font-size:10px; color:var(--muted); text-transform:uppercase;
  letter-spacing:1.2px; padding:8px 12px 6px;
  border-bottom:1px solid var(--border); flex-shrink:0;
}

/* steps */
#steps-wrap{ flex:0 0 auto; padding:8px 10px; }
.step{
  display:flex; align-items:center; gap:8px;
  padding:5px 6px; border-radius:var(--r);
  border:1px solid transparent; margin-bottom:3px;
  transition:all var(--t);
}
.si{ width:16px; text-align:center; font-size:12px; flex-shrink:0; }
.sl{ font-size:11px; color:var(--muted); flex:1; }
.step[data-s=wait]   .si{ color:var(--muted); }
.step[data-s=active]{ border-color:var(--gdim); background:var(--bg3); }
.step[data-s=active] .si{ color:var(--green); animation:blink .8s step-end infinite; }
.step[data-s=active] .sl{ color:var(--green); }
.step[data-s=done]   .si{ color:var(--gdim); }
.step[data-s=done]   .sl{ color:var(--gdim); }
.step[data-s=err]   { border-color:#3a0808; background:#100303; }
.step[data-s=err]    .si{ color:var(--red); }
.step[data-s=err]    .sl{ color:var(--red); }
.step[data-s=skip]   .sl{ color:var(--amber); }
@keyframes blink{ 50%{ opacity:.3; } }

/* controls */
#ctrl{ flex:1; overflow-y:auto; padding:10px 10px; display:flex; flex-direction:column; gap:10px; }
.clabel{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }
select, .path-in{
  width:100%; background:var(--bg3); color:var(--text);
  border:1px solid var(--border); border-radius:var(--r);
  padding:5px 8px; font-family:var(--f); font-size:11px;
  outline:none; appearance:none;
}
select:focus, .path-in:focus{ border-color:var(--gdim); }
.row2{ display:flex; gap:4px; }
.row2 .path-in{ flex:1; min-width:0; }
btn{ all:unset; }
button{
  background:var(--bg3); color:var(--text); border:1px solid var(--border);
  border-radius:var(--r); padding:5px 10px; font-family:var(--f); font-size:11px;
  cursor:pointer; transition:all var(--t); white-space:nowrap;
}
button:hover:not(:disabled){ border-color:var(--gdim); color:var(--green); }
button:disabled{ opacity:.38; cursor:not-allowed; }
button.primary{
  background:var(--glo); border-color:var(--gdim); color:var(--green);
  font-weight:700; letter-spacing:1px; padding:8px;
  text-shadow:0 0 6px rgba(57,255,20,.4);
}
button.primary:hover:not(:disabled){
  background:#0e3a0e; box-shadow:0 0 10px rgba(57,255,20,.18);
}
button.danger{ border-color:#3a0a0a; color:var(--red); }
button.danger:hover:not(:disabled){ background:#120303; border-color:var(--red); }

/* progress */
#prog-wrap{ display:none; }
#prog-bg{ height:4px; background:var(--bg3); border:1px solid var(--border); border-radius:2px; overflow:hidden; margin-bottom:3px; }
#prog-bar{ height:100%; width:0%; background:var(--green); transition:width .3s; box-shadow:0 0 6px rgba(57,255,20,.5); }
#prog-lbl{ font-size:10px; color:var(--muted); }

/* disk info */
#disk-info{ font-size:10.5px; color:var(--muted); line-height:1.7; }

/* ventoy status */
#vtoy-status{ font-size:10px; padding:5px 8px; border-radius:var(--r);
  border:1px solid var(--border); line-height:1.5; }
#vtoy-status.found{ border-color:var(--glo); color:var(--gdim); }
#vtoy-status.missing{ border-color:#3a2800; color:var(--amber); }

/* admin warn */
#admin-warn{
  background:#120a00; border:1px solid #3a2000;
  border-radius:var(--r); padding:6px 8px;
  font-size:10px; color:var(--amber); line-height:1.5; display:none;
}

/* ── log panel ── */
#right{ flex:1; display:flex; flex-direction:column; overflow:hidden; }
#log-header{
  display:flex; align-items:center; gap:8px;
  padding:7px 12px 5px; border-bottom:1px solid var(--border); flex-shrink:0;
}
#log-title{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:1.2px; }
#log-lcount{ font-size:10px; color:var(--muted); margin-left:auto; }
#log-wrap{ flex:1; overflow-y:auto; padding:8px 14px; }
#log{ font-size:11.5px; line-height:1.65; white-space:pre-wrap; word-break:break-all; }
.lOK  { color:var(--green); }
.lINF { color:var(--text); }
.lWRN { color:var(--amber); }
.lERR { color:var(--red); }
.lCMD { color:var(--cyan); }
.lSTP { color:var(--green); font-weight:700; }
.lDIM { color:var(--muted); }

/* ── statusbar ── */
#statusbar{
  height:24px; background:var(--bg2); border-top:1px solid var(--border);
  display:flex; align-items:center; padding:0 12px;
  font-size:10.5px; color:var(--muted); gap:14px; flex-shrink:0;
}
#sb-msg{ color:var(--text); }
#sb-time{ margin-left:auto; }
.dot{ display:inline-block; width:6px; height:6px; border-radius:50%;
  background:var(--gdim); margin-right:5px; animation:pulse 2s infinite; }
@keyframes pulse{ 0%,100%{ opacity:.35; } 50%{ opacity:1; } }
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">⬡ AvalOS</span>
  <span class="logo-sub">USB Maker v2 · AvalOS + Ventoy</span>
  <div id="topbar-right">
    <span id="badge-admin" class="tbadge dim">Admin ···</span>
    <span id="badge-net"   class="tbadge dim">Net ···</span>
  </div>
</div>

<div id="layout">

  <!-- ── SIDEBAR ── -->
  <div id="sidebar">
    <div class="phead">▸ Progreso</div>
    <div id="steps-wrap">
      <div class="step" id="st-detect" data-s="wait"><span class="si">◌</span><span class="sl">Detectar USB</span></div>
      <div class="step" id="st-ventoy" data-s="wait"><span class="si">◌</span><span class="sl">Instalar Ventoy</span></div>
      <div class="step" id="st-iso"    data-s="wait"><span class="si">◌</span><span class="sl">Copiar ISO</span></div>
      <div class="step" id="st-script" data-s="wait"><span class="si">◌</span><span class="sl">Copiar instalador AvalOS</span></div>
      <div class="step" id="st-done"   data-s="wait"><span class="si">◌</span><span class="sl">¡USB lista!</span></div>
    </div>

    <div id="ctrl">
      <!-- Disco USB -->
      <div>
        <div class="clabel">Disco USB destino</div>
        <div class="row2">
          <select id="usb-sel"><option value="">— detectando —</option></select>
          <button id="btn-refresh" title="Refrescar" onclick="loadDisks()">↺</button>
        </div>
        <div id="disk-info" style="margin-top:5px">—</div>
      </div>

      <!-- ISO -->
      <div>
        <div class="clabel">ISO de Arch Linux</div>
        <div class="row2">
          <input class="path-in" id="iso-path" type="text" placeholder="ruta al .iso..." readonly>
          <button id="btn-browse" onclick="browseISO()">…</button>
        </div>
      </div>

      <!-- Ventoy -->
      <div>
        <div class="clabel">Ventoy</div>
        <div id="vtoy-status" class="missing">Buscando Ventoy…</div>
        <div class="row2" style="margin-top:5px">
          <button id="btn-vtoy-dl" onclick="downloadVentoy()" style="flex:1">⬇ Descargar Ventoy</button>
          <button id="btn-vtoy-browse" onclick="browseVentoy()" title="Seleccionar Ventoy2Disk.exe manualmente">…</button>
        </div>
      </div>

      <div id="admin-warn">
        ⚠ Se necesitan privilegios de Administrador.<br>
        Cierra y vuelve a ejecutar como Admin.
      </div>

      <div id="prog-wrap">
        <div id="prog-bg"><div id="prog-bar"></div></div>
        <div id="prog-lbl">0%</div>
      </div>

      <button class="primary" id="btn-start" disabled onclick="startProcess()">▶ Preparar USB</button>
      <button class="danger"  id="btn-abort" disabled  onclick="abortProcess()">■ Abortar</button>
    </div>
  </div>

  <!-- ── LOG ── -->
  <div id="right">
    <div id="log-header">
      <span id="log-title">▸ log</span>
      <span id="log-lcount">0 líneas</span>
    </div>
    <div id="log-wrap"><pre id="log"><span class="lDIM">╔══════════════════════════════════════════════════════════╗
║   AvalOS USB Maker v2 · Ventoy edition                   ║
╚══════════════════════════════════════════════════════════╝

</span><span class="lINF">Selecciona un disco USB y el ISO de AvalOS.
Pulsa ▶ Preparar USB cuando estés listo.

</span><span class="lWRN">⚠  TODOS LOS DATOS del disco USB serán borrados por Ventoy.
</span></pre></div>
    <div id="statusbar">
      <span><span class="dot"></span><span id="sb-msg">esperando configuración</span></span>
      <span id="sb-time"></span>
    </div>
  </div>
</div>

<script>
// ── Estado ──────────────────────────────────────────────────────────────────
let disks = [], running = false, logLines = 0, timer = null, startT = 0;

// ── DOM helpers ─────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function alog(txt, cls = 'lINF') {
  const s = document.createElement('span');
  s.className = cls; s.textContent = txt + '\n';
  $('log').appendChild(s);
  logLines++;
  $('log-lcount').textContent = logLines + ' líneas';
  $('log-wrap').scrollTop = $('log-wrap').scrollHeight;
}
function setStep(id, state) {
  const el = $('st-' + id); if (!el) return;
  el.dataset.s = state;
  const icons = { wait:'◌', active:'◎', done:'●', err:'✗', skip:'○' };
  el.querySelector('.si').textContent = icons[state] || '◌';
}
function setStatus(t) { $('sb-msg').textContent = t; }
function setProg(pct, lbl) {
  $('prog-wrap').style.display = 'block';
  $('prog-bar').style.width = Math.min(100,pct) + '%';
  $('prog-lbl').textContent = lbl || pct + '%';
}
function startTimer() {
  startT = Date.now(); clearInterval(timer);
  timer = setInterval(() => {
    const s = Math.floor((Date.now()-startT)/1000);
    $('sb-time').textContent = Math.floor(s/60)+'m '+(s%60)+'s';
  }, 1000);
}
function stopTimer() { clearInterval(timer); }
function updateStart() {
  const ok = $('usb-sel').value !== '' && $('iso-path').value !== '' && !running;
  $('btn-start').disabled = !ok;
}

// ── Discos ──────────────────────────────────────────────────────────────────
async function loadDisks() {
  $('usb-sel').innerHTML = '<option value="">— detectando —</option>';
  $('disk-info').textContent = '…';
  setStep('detect','active');
  try {
    const raw = await window.pywebview.api.get_usb_disks();
    disks = JSON.parse(raw);
    $('usb-sel').innerHTML = '';
    if (!disks.length) {
      $('usb-sel').innerHTML = '<option value="">— sin USBs detectadas —</option>';
      setStep('detect','skip');
      alog('[WARN] No se detectaron USBs. Conecta la USB y pulsa ↺', 'lWRN');
    } else {
      $('usb-sel').add(new Option('— seleccionar —',''));
      disks.forEach(d => $('usb-sel').add(new Option(`Disk ${d.number} · ${d.size_gb} GB · ${d.name}`, d.number)));
      setStep('detect','done');
      alog(`[OK] ${disks.length} USB(s) detectada(s).`, 'lOK');
    }
  } catch(e) { setStep('detect','err'); alog('[ERR] '+e,'lERR'); }
  updateStart();
}
$('usb-sel').addEventListener('change', () => {
  const d = disks.find(x => x.number == $('usb-sel').value);
  $('disk-info').textContent = d
    ? `Modelo: ${d.name}  |  ${d.size_gb} GB  |  Disk ${d.number}`
    : '—';
  updateStart();
});

// ── Ventoy ──────────────────────────────────────────────────────────────────
async function checkVentoy() {
  const r = await window.pywebview.api.find_ventoy();
  const res = JSON.parse(r);
  const el = $('vtoy-status');
  if (res.found) {
    el.className = 'vtoy-status found';
    el.style.cssText='border-color:var(--glo);color:var(--gdim);padding:5px 8px;border-radius:4px;border:1px solid;font-size:10px;line-height:1.5;';
    el.textContent = `✓ Ventoy ${res.version || ''} — ${res.path}`;
    alog(`[OK] Ventoy encontrado: ${res.path}`, 'lOK');
  } else {
    el.className = 'vtoy-status missing';
    el.style.cssText='border-color:#3a2800;color:var(--amber);padding:5px 8px;border-radius:4px;border:1px solid;font-size:10px;line-height:1.5;';
    el.textContent = '⚠ Ventoy no encontrado — descárgalo o selecciónalo';
  }
}
async function downloadVentoy() {
  $('btn-vtoy-dl').disabled = true;
  $('btn-vtoy-dl').textContent = '⬇ Descargando…';
  alog('\n── Descargando Ventoy ──', 'lSTP');
  setStatus('Descargando Ventoy…');
  try {
    const r = await window.pywebview.api.download_ventoy();
    const res = JSON.parse(r);
    if (res.ok) {
      alog('[OK] Ventoy descargado: ' + res.path, 'lOK');
      await checkVentoy();
    } else {
      alog('[ERR] ' + res.error, 'lERR');
    }
  } catch(e) { alog('[ERR] '+e,'lERR'); }
  $('btn-vtoy-dl').disabled = false;
  $('btn-vtoy-dl').textContent = '⬇ Descargar Ventoy';
  setStatus('listo');
}
async function browseVentoy() {
  const p = await window.pywebview.api.browse_ventoy();
  if (p) { alog('[OK] Ventoy2Disk.exe: '+p,'lOK'); await checkVentoy(); }
}

// ── ISO ──────────────────────────────────────────────────────────────────────
async function browseISO() {
  const p = await window.pywebview.api.browse_iso();
  if (p) { $('iso-path').value = p; setStep('iso','done'); alog('[OK] ISO: '+p,'lOK'); }
  updateStart();
}

// ── Proceso principal ────────────────────────────────────────────────────────
async function startProcess() {
  const diskNum = $('usb-sel').value;
  const isoPath = $('iso-path').value;
  if (!diskNum || !isoPath) return;
  const disk = disks.find(d => d.number == diskNum);
  const ok = await window.pywebview.api.confirm_write(
    diskNum, disk?.name || '?', disk?.size_gb || '?', isoPath);
  if (!ok) return;
  running = true;
  $('btn-start').disabled = true;
  $('btn-abort').disabled = false;
  $('btn-refresh').disabled = true;
  $('btn-browse').disabled = true;
  $('usb-sel').disabled = true;
  startTimer();
  alog('\n══ Iniciando preparación USB ══\n','lSTP');
  await window.pywebview.api.start_process(diskNum, isoPath);
}
async function abortProcess() {
  await window.pywebview.api.abort();
  alog('\n[USUARIO] Proceso abortado.','lWRN');
}
function unlockUI() {
  running = false;
  $('btn-abort').disabled = true;
  $('btn-refresh').disabled = false;
  $('btn-browse').disabled = false;
  $('usb-sel').disabled = false;
  updateStart(); stopTimer();
}

// ── Callbacks Python → JS ────────────────────────────────────────────────────
function pyLog(t,c)        { alog(t,'l'+(c||'INF')); }
function pyStep(id,s)      { setStep(id,s); }
function pyProgress(p,l)   { setProg(p,l); }
function pyStatus(t)       { setStatus(t); }
function pyAdminWarn()     { $('admin-warn').style.display='block'; }
function pyDone() {
  unlockUI(); setStatus('✓ USB lista — arranca desde ella para instalar AvalOS');
  alog('\n╔══════════════════════════════════════════════════╗\n║  ✓ USB lista — AvalOS listo para bootear        ║\n╠══════════════════════════════════════════════════╣\n║  1. Inserta la USB y arranca desde ella          ║\n║     (BIOS/UEFI → selecciona la USB)             ║\n║  2. Ventoy muestra el menú → selecciona AvalOS  ║\n║  3. SDDM abre → Hyprland live (autologin root)  ║\n║  4. El instalador gráfico se abre SOLO ✓        ║\n║     Si lo cerraste: Super+I para reabrirlo      ║\n╚══════════════════════════════════════════════════╝\n','lOK');
}
function pyError(msg) {
  unlockUI(); setStatus('error — revisa el log');
  alog('\n[ERROR] '+msg,'lERR');
  setStep('done','err');
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('pywebviewready', async () => {
  loadDisks();
  const admin = await window.pywebview.api.check_admin();
  $('badge-admin').textContent = admin ? 'Admin ✓' : 'Sin Admin ⚠';
  $('badge-admin').className = 'tbadge ' + (admin ? 'ok' : 'err');
  if (!admin) pyAdminWarn();
  const net = await window.pywebview.api.check_net();
  $('badge-net').textContent = net ? 'Net ✓' : 'Sin Red';
  $('badge-net').className = 'tbadge ' + (net ? 'ok' : 'err');
  await checkVentoy();
});
</script>
</body>
</html>
"""

# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES WINDOWS
# ══════════════════════════════════════════════════════════════════════════════

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _run_ps(cmd: str, timeout: int = 30) -> tuple[int, str]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return r.returncode, (r.stdout + r.stderr).strip()

def _check_net() -> bool:
    try:
        urlopen("https://www.google.com", timeout=4)
        return True
    except Exception:
        return False

def _get_usb_disks() -> list[dict]:
    rc, out = _run_ps(
        "Get-Disk | Where-Object {$_.BusType -eq 'USB'} | "
        "Select-Object Number,FriendlyName,"
        "@{N='SizeGB';E={[math]::Round($_.Size/1GB,1)}} | "
        "ConvertTo-Json -Depth 2"
    )
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return [
            {"number": int(d["Number"]),
             "name":   str(d.get("FriendlyName", "USB")),
             "size_gb": round(float(d.get("SizeGB") or 0), 1)}
            for d in data if float(d.get("SizeGB") or 0) >= MIN_USB_GB
        ]
    except Exception:
        return []

def _find_exe_dir() -> Path:
    """Devuelve la carpeta donde vive el ejecutable/script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

def _find_ventoy_exe() -> Path | None:
    """Busca Ventoy2Disk.exe en la carpeta del exe y subcarpetas inmediatas."""
    base = _find_exe_dir()
    patterns = [
        base / "Ventoy2Disk.exe",
        *base.glob("ventoy-*/Ventoy2Disk.exe"),
        *base.glob("ventoy*/Ventoy2Disk.exe"),
    ]
    for p in patterns:
        if p.exists():
            return p
    return None

def _ventoy_version(exe: Path) -> str:
    """Extrae la versión de Ventoy del nombre de carpeta o del exe."""
    for part in exe.parts:
        if part.startswith("ventoy-"):
            return part.replace("ventoy-", "").replace("-windows", "")
    return ""

def _get_latest_ventoy_url() -> tuple[str, str]:
    """Devuelve (url_zip, version) de la última release de GitHub."""
    try:
        with urlopen(VENTOY_API_URL, timeout=8) as r:
            data = json.loads(r.read())
        tag = data["tag_name"].lstrip("v")
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if "windows" in name.lower() and name.endswith(".zip"):
                return asset["browser_download_url"], tag
    except Exception:
        pass
    return VENTOY_FALLBACK, VENTOY_VERSION

def _get_drive_letter(disk_num: int) -> str | None:
    """Devuelve la letra de la partición data de Ventoy (ExFAT, etiqueta Ventoy)."""
    rc, out = _run_ps(
        f"Get-Partition -DiskNumber {disk_num} | Get-Volume | "
        "Where-Object { $_.FileSystem -eq 'exFAT' -or $_.FileSystemLabel -like 'Ventoy' } | "
        "Select-Object -First 1 -ExpandProperty DriveLetter"
    )
    if rc == 0 and out.strip():
        return out.strip()[0].upper()
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  API PYWEBVIEW
# ══════════════════════════════════════════════════════════════════════════════

class GAIAAPI:
    def __init__(self, app: "GAIAApp"):
        self._a = app

    def check_admin(self) -> bool:
        return _is_admin()

    def check_net(self) -> bool:
        return _check_net()

    def get_usb_disks(self) -> str:
        return json.dumps(_get_usb_disks())

    def find_ventoy(self) -> str:
        exe = _find_ventoy_exe()
        if exe:
            return json.dumps({"found": True, "path": str(exe), "version": _ventoy_version(exe)})
        return json.dumps({"found": False})

    def browse_iso(self) -> str:
        result = self._a.win.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("AvalOS ISO (*.iso)", "All Files (*.*)")
        )
        return result[0] if result else ""

    def browse_ventoy(self) -> str:
        result = self._a.win.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("Ventoy2Disk.exe (*.exe)", "All Files (*.*)")
        )
        if result:
            # Mover/copiar al lado del exe para que find_ventoy lo detecte
            dst = _find_exe_dir() / "Ventoy2Disk.exe"
            if Path(result[0]) != dst:
                shutil.copy2(result[0], dst)
            return str(dst)
        return ""

    def download_ventoy(self) -> str:
        try:
            url, ver = _get_latest_ventoy_url()
            self._a._jsc("pyLog", f"  URL: {url}", "INF")
            tmp_zip = Path(tempfile.mktemp(suffix=".zip"))

            def progress(blocks, bsize, total):
                if total > 0:
                    pct = int(blocks * bsize / total * 100)
                    self._a._jsc("pyProgress", min(pct, 99), f"Descargando Ventoy… {pct}%")

            urlretrieve(url, tmp_zip, progress)
            # Extraer junto al exe
            dest = _find_exe_dir()
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(dest)
            tmp_zip.unlink(missing_ok=True)
            self._a._jsc("pyProgress", 100, "Ventoy descargado")
            exe = _find_ventoy_exe()
            return json.dumps({"ok": True, "path": str(exe) if exe else str(dest)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def confirm_write(self, disk_num: str, disk_name: str, disk_size: str, iso_path: str) -> bool:
        msg = (
            f"¿Confirmas?\n\n"
            f"  Disco:  Disk {disk_num} · {disk_name} · {disk_size} GB\n"
            f"  ISO:    {Path(iso_path).name}\n\n"
            f"⚠  TODOS LOS DATOS del disco serán destruidos por Ventoy.\n"
            f"   Esta acción no se puede deshacer."
        )
        return bool(self._a.win.create_confirmation_dialog("GAIA — Confirmar", msg))

    def start_process(self, disk_num: str, iso_path: str):
        threading.Thread(
            target=self._a._run,
            args=(int(disk_num), iso_path),
            daemon=True
        ).start()

    def abort(self):
        self._a._aborted = True

# ══════════════════════════════════════════════════════════════════════════════
#  APLICACIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class GAIAApp:
    def __init__(self):
        self.win: webview.Window | None = None
        self._aborted = False

    def _jsc(self, fn: str, *args):
        if not self.win:
            return
        parts = [json.dumps(a, ensure_ascii=False) for a in args]
        try:
            self.win.evaluate_js(f"{fn}({','.join(parts)})")
        except Exception:
            pass

    def _log(self, msg: str, cls: str = "INF"):
        self._jsc("pyLog", msg, cls)

    def _step(self, sid: str, state: str):
        self._jsc("pyStep", sid, state)

    def _prog(self, pct: int, lbl: str = ""):
        self._jsc("pyProgress", pct, lbl)

    def _status(self, t: str):
        self._jsc("pyStatus", t)

    # ── Proceso completo ─────────────────────────────────────────────────────

    def _run(self, disk_num: int, iso_path: str):
        self._aborted = False
        try:
            # 1. Validar admin
            if not _is_admin():
                self._jsc("pyAdminWarn")
                self._jsc("pyError", "Ejecuta como Administrador.")
                return

            # 2. Validar Ventoy
            ventoy_exe = _find_ventoy_exe()
            if not ventoy_exe:
                self._jsc("pyError",
                    "Ventoy2Disk.exe no encontrado.\n"
                    "Descárgalo con el botón ⬇ o selecciónalo con …")
                return

            # 3. Validar ISO
            iso = Path(iso_path)
            if not iso.exists():
                self._jsc("pyError", f"ISO no encontrado: {iso_path}")
                return

            iso_gb = iso.stat().st_size / 1024**3
            self._log(f"  ISO:    {iso.name}  ({iso_gb:.2f} GB)", "INF")
            self._log(f"  Disk:   {disk_num}", "INF")
            self._log(f"  Ventoy: {ventoy_exe}", "INF")

            # 4. Instalar Ventoy
            self._step("ventoy", "active")
            self._status(f"Instalando Ventoy en Disk {disk_num}…")
            self._log("\n── Instalando Ventoy ──\n", "STP")

            vtoy_cmd = [
                str(ventoy_exe),
                "-I",                       # Install (overwrite existing)
                "-s",                       # Silent — no GUI de Ventoy
                "-g",                       # GPT en lugar de MBR
                f"\\\\.\\PhysicalDrive{disk_num}"
            ]
            self._log(f"$ {' '.join(vtoy_cmd)}", "CMD")
            rc = subprocess.run(
                vtoy_cmd, capture_output=True, text=True, timeout=120
            )
            out_vtoy = (rc.stdout + rc.stderr).strip()
            for line in out_vtoy.splitlines():
                if line.strip():
                    self._log(f"  {line.strip()}", "DIM")

            if rc.returncode != 0:
                self._step("ventoy", "err")
                # Ventoy a veces devuelve rc!=0 pero si igual funciona
                # Verificar que se creó la partición ExFAT
                self._log("[WARN] Ventoy reportó un error — verificando particiones…", "WRN")

            # Esperar a que Windows monte las nuevas particiones
            time.sleep(3)
            drive = _get_drive_letter(disk_num)
            if not drive:
                # Segundo intento más lento
                time.sleep(5)
                drive = _get_drive_letter(disk_num)

            if not drive:
                self._step("ventoy", "err")
                self._jsc("pyError",
                    "Ventoy se instaló pero Windows no montó la partición data.\n\n"
                    "Solución: desconecta y reconecta la USB, "
                    "luego copia manualmente el ISO y el script a la unidad Ventoy.")
                return

            self._step("ventoy", "done")
            self._prog(25, "Ventoy instalado")
            self._log(f"  ✓ Ventoy instalado — partición data en {drive}:\\", "OK")
            time.sleep(0.5)

            if self._aborted:
                return

            # 5. Copiar ISO a la partición Ventoy
            self._step("iso", "active")
            self._status(f"Copiando ISO a {drive}:\\…")
            self._log(f"\n── Copiando ISO → {drive}:\\ ──\n", "STP")

            dest_iso = Path(f"{drive}:\\") / iso.name
            iso_size = iso.stat().st_size
            copied = 0
            t0 = time.time()
            CHUNK = 4 * 1024 * 1024

            with open(iso, "rb") as src, open(dest_iso, "wb") as dst:
                while True:
                    if self._aborted:
                        self._jsc("pyError", "Abortado durante copia del ISO.")
                        return
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    pct = 25 + int(copied / iso_size * 55)   # 25-80%
                    elapsed = max(time.time() - t0, 0.1)
                    mbs = (copied / 1024**2) / elapsed
                    self._prog(pct, f"{pct}% · {mbs:.1f} MB/s")

            self._step("iso", "done")
            self._prog(82, "ISO copiado")
            self._log(f"  ✓ {iso.name} copiado ({iso_gb:.2f} GB)", "OK")

            if self._aborted:
                return

            # 6. Copiar instalador GAIA + launcher
            self._step("script", "active")
            self._status("Copiando instalador GAIA…")
            self._log(f"\n── Copiando instalador → {drive}:\\ ──\n", "STP")

            dest_dir = Path(f"{drive}:\\")

            # skill_instalar_usb.py
            script_src = _find_exe_dir() / SCRIPT_NAME
            if script_src.exists():
                shutil.copy2(script_src, dest_dir / SCRIPT_NAME)
                kb = script_src.stat().st_size // 1024
                self._log(f"  [ok] {SCRIPT_NAME}  ({kb} KB)", "OK")
            else:
                self._log(
                    f"[WARN] {SCRIPT_NAME} no encontrado junto al exe.\n"
                    f"  Cópialo manualmente a {drive}:\\ antes de bootear.", "WRN"
                )

            # lanzar_avalos.sh
            (dest_dir / LAUNCHER_NAME).write_text(LAUNCHER_SH, encoding="utf-8")
            self._log(f"  [ok] {LAUNCHER_NAME}", "OK")

            # INSTRUCCIONES.txt
            instrucciones = (
                "AvalOS — USB lista\n"
                "══════════════════════════════════════════════\n\n"
                "FLUJO COMPLETO:\n\n"
                "1. Inserta esta USB en tu PC y arranca desde ella\n"
                "   (BIOS/UEFI → selecciona la USB como boot device)\n\n"
                "2. Ventoy mostrará un menú → selecciona el ISO de AvalOS\n\n"
                "3. SDDM abrirá Hyprland live automáticamente\n\n"
                "4. El instalador gráfico se abre SOLO (wizard azul Tokyo Night)\n"
                "   · Si lo cierras: Super+I para reabrirlo\n"
                "   · O desde Waybar: botón Instalar AvalOS (barra superior)\n\n"
                "5. Completa el wizard:\n"
                "   · Selecciona el disco destino (ej: tu USB de 128GB)\n"
                "   · Nombre de usuario / Contraseña / Hostname / Timezone\n"
                "   · Modo: USB Persistente (recomendado para USB)\n"
                "          o Disco (para HDD/SSD)\n"
                "   · Bootloader: GRUB (recomendado)\n"
                "   · Pulsa INSTALAR AVALOS\n\n"
                "6. Reinicia sin el USB de instalación → SDDM → Hyprland\n\n"
                "NOTA: Si quieres instalar EN esta misma USB (128GB+)\n"
                "necesitas bootear el live desde un SEGUNDO USB o PC.\n\n"
                "El sistema instala: AvalOS (Arch) + Hyprland + Waybar + SDDM\n"
                "Tema: Tokyo Night PRO · AMD GPU optimizado\n"
            )
            (dest_dir / "INSTRUCCIONES.txt").write_text(instrucciones, encoding="utf-8")
            self._log("  [ok] INSTRUCCIONES.txt", "OK")

            self._step("script", "done")
            self._prog(100, "✓ completado")
            self._step("done", "done")
            self._jsc("pyDone")

        except PermissionError:
            self._jsc("pyError", "Permiso denegado. Asegúrate de ejecutar como Administrador.")
        except Exception as e:
            self._jsc("pyError", str(e))

# ══════════════════════════════════════════════════════════════════════════════
#  PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Auto-elevación si no somos admin
    if sys.platform == "win32" and not _is_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit(0)
        except Exception:
            pass

    app  = GAIAApp()
    api  = GAIAAPI(app)

    win = webview.create_window(
        title            = "AvalOS — USB Maker",
        html             = _HTML,
        js_api           = api,
        width            = 920,
        height           = 580,
        min_size         = (720, 480),
        resizable        = True,
        background_color = "#020c02",
    )
    app.win = win
    webview.start(debug=False)

if __name__ == "__main__":
    main()
