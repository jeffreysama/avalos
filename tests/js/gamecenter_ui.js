// Prueba de humo del front-end de avalos-gamecenter con jsdom (sin navegador).
//   node gamecenter_ui.js <pagina.html> <idioma>      (jsdom en NODE_PATH)
// Una línea "ok: ..." por comprobación; sale con 1 en la primera que falle.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [, , file, lang] = process.argv;
const html = fs.readFileSync(file, 'utf8');
const STR = JSON.parse(/const S = (\{.*?\});\nconst LAUNCHERS/s.exec(html)[1]);
const tick = () => new Promise((r) => setTimeout(r, 15));
let n = 0;
function check(cond, what) { n++; if (!cond) { console.log('FALLA: ' + what); process.exit(1); } console.log('ok: ' + what); }

const BASE = () => ({
  launchers: { steam: true, lutris: false, heroic: true, prism: false, bottles: false },
  gamemode: { installed: true, state: 'idle', in_group: true, governor: 'powersave', driver: 'amd-pstate-epp', epp: 'balance_performance', target: 'performance', whitelist: ['steam', 'lutris'] },
  mango: { installed: true, active: 'standard', has_backup: false, profiles: ['minimal', 'standard', 'full', 'hidden'] },
  tools: [], system: { gpus: ['AMD · amdgpu'], monitors: [{ name: 'DP-1', mode: '2560×1440 @ 165 Hz', vrr: true }] },
});
const OPTS = (p) => ({ gamemode: 'gamemoderun %command%', mangohud: 'mangohud %command%', both: 'mangohud gamemoderun %command%',
  profile: 'MANGOHUD_CONFIGFILE=PROFILE-' + p + ' mangohud gamemoderun %command%' });

async function boot(snapshot, over = {}) {
  const calls = []; const errors = [];
  const api = {
    snapshot: async () => snapshot,
    open_launcher: async (id) => { calls.push(['open_launcher', id]); return true; },
    open_store: async () => { calls.push(['open_store']); return true; },
    gamemode_test: async () => { calls.push(['gamemode_test']); return { state: 'done', passed: 6, failed: 0, output: '' }; },
    mango_apply: async (id) => { calls.push(['mango_apply', id]); return Object.assign({}, snapshot.mango, { active: id }); },
    mango_restore: async () => { calls.push(['mango_restore']); return Object.assign({}, snapshot.mango, { active: 'custom', has_backup: true }); },
    launch_options: async (p) => { calls.push(['launch_options', p]); return OPTS(p); },
    copy_options: async (v, p) => { calls.push(['copy_options', v, p]); return { ok: true, text: '' }; },
    close: async () => { calls.push(['close']); },
  };
  Object.assign(api, over);
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) {
    w.addEventListener('error', (e) => errors.push(String(e.error || e.message)));
    w.pywebview = { api };
  } });
  const w = dom.window; const d = w.document;
  return { w, d, calls, errors, q: (s) => d.querySelector(s), qa: (s) => Array.from(d.querySelectorAll(s)),
    ready: async () => { w.dispatchEvent(new w.Event('pywebviewready')); await tick(); await tick(); } };
}

(async () => {
  // ── carga ───────────────────────────────────────────────────────────────
  let p = await boot(BASE());
  check(p.d.documentElement.lang === (lang === 'zh' ? 'zh-CN' : lang), 'lang del documento');
  check(p.q('#title').textContent === STR.title, 'título');
  check(p.q('#loading').textContent === STR.loading && p.q('#content').classList.contains('hidden'), 'antes de cargar: mensaje de lectura');
  await p.ready();
  check(p.q('#loading').classList.contains('hidden') && !p.q('#content').classList.contains('hidden'), 'tras cargar: contenido visible');
  check(p.qa('#content h2').length === 6, '6 secciones');

  // ── lanzadores ──────────────────────────────────────────────────────────
  check(p.qa('[data-launcher]').length === 5, '5 lanzadores');
  check(p.q('[data-launcher="steam"]').querySelector('.d').textContent === STR['d-steam'] && !p.q('[data-launcher="steam"]').disabled, 'instalado: activo con su descripción');
  check(p.q('[data-launcher="lutris"]').disabled && p.q('[data-launcher="lutris"]').querySelector('.d').textContent === STR['l-missing'], 'no instalado: desactivado y con aviso');
  p.q('[data-launcher="heroic"]').click(); await tick();
  check(JSON.stringify(p.calls.at(-1)) === '["open_launcher","heroic"]', 'clic abre el lanzador correcto');
  p.q('#store-btn').click(); await tick();
  check(JSON.stringify(p.calls.at(-1)) === '["open_store"]', 'botón de la Tienda');
  let q2 = await boot(BASE(), { open_launcher: async () => false }); await q2.ready();
  q2.q('[data-launcher="steam"]').click(); await tick();
  check(!q2.q('#toast').classList.contains('hidden') && q2.q('#toast').textContent === STR['l-missing'], 'si no se puede abrir: aviso');

  // ── GameMode ────────────────────────────────────────────────────────────
  const gmText = () => p.qa('#content .card')[0].querySelector('.status').textContent;
  check(gmText() === STR['gm-idle'] && p.q('.status .dot.idle'), 'GameMode listo');
  check(p.qa('#content .card')[0].querySelector('.facts').textContent.includes('powersave') && p.q('.facts').textContent.includes('steam, lutris'), 'datos del gobernador y programas');
  check(p.qa('#content .card')[0].querySelector('.note.ok').textContent === STR['gm-group-ok'], 'grupo gamemode: ok');
  const mkGm = async (g) => { const s = BASE(); Object.assign(s.gamemode, g); const x = await boot(s); await x.ready(); return x; };
  let x = await mkGm({ state: 'active' });
  check(x.q('.status').textContent === STR['gm-active'] && x.q('.status .dot.active'), 'GameMode activo');
  x = await mkGm({ state: 'unknown' }); check(x.q('.status').textContent === STR['gm-unknown'], 'GameMode con estado ilegible');
  x = await mkGm({ in_group: false }); check(x.q('.note.warn').textContent === STR['gm-group-no'], 'grupo gamemode: aviso de volver a entrar');
  x = await mkGm({ in_group: null }); check(x.q('.note.warn').textContent === STR['gm-group-na'], 'grupo gamemode inexistente');
  x = await mkGm({ installed: false, state: 'missing' });
  check(x.q('.status').textContent === STR['gm-missing'] && !x.q('#gm-test-btn') && !x.qa('#content .card')[0].querySelector('.facts'), 'sin GameMode: aviso, sin botón ni datos');
  p.q('#gm-test-btn').click();
  check(p.q('#gm-test-btn').disabled && p.q('#gm-test-btn').textContent === STR['gm-testing'], 'prueba: botón en «Probando…»');
  await tick();
  check(p.q('#gm-test-res .note.ok').textContent === STR['gm-test-ok'].replace('{n}', '6') && !p.q('#gm-test-btn').disabled, 'prueba aprobada');
  x = await boot(BASE(), { gamemode_test: async () => ({ state: 'done', passed: 4, failed: 2, output: 'x' }) }); await x.ready();
  x.q('#gm-test-btn').click(); await tick();
  check(x.q('#gm-test-res .note').textContent === STR['gm-test-fail'].replace('{n}', '2'), 'prueba con fallos');
  x = await boot(BASE(), { gamemode_test: async () => ({ state: 'error', output: '<b>traza</b>' }) }); await x.ready();
  x.q('#gm-test-btn').click(); await tick();
  check(x.q('#gm-test-res .note.bad').textContent === STR['gm-test-err'] && x.q('#gm-test-res pre').textContent === '<b>traza</b>' && !x.q('#gm-test-res b'), 'prueba que no termina: aviso y salida como texto');

  // ── MangoHud ────────────────────────────────────────────────────────────
  check(p.q('#mg-state').textContent === STR['mg-state'] + ' ' + STR['mp-standard'], 'perfil en uso');
  check(p.qa('[data-profile]').length === 4 && p.q('[data-profile="standard"]').classList.contains('on'), '4 perfiles, el activo marcado');
  check(p.q('[data-profile="standard"] button').disabled && p.q('[data-profile="standard"] button').textContent === STR['mg-current'], 'el perfil en uso no se puede volver a aplicar');
  p.q('[data-profile="full"] button').click(); await tick(); await tick();
  check(JSON.stringify(p.calls.filter((c) => c[0] === 'mango_apply').at(-1)) === '["mango_apply","full"]', 'aplicar un perfil llama a la API');
  check(p.q('#toast').textContent === STR['mg-applied'].replace('{name}', STR['mp-full']) && p.q('[data-profile="full"]').classList.contains('on'), 'aviso y el perfil nuevo queda marcado');
  check(p.q('#lo-profile').value === 'full' && p.q('[data-variant="profile"] code').textContent.includes('PROFILE-full'), 'las opciones de lanzamiento siguen al perfil aplicado');
  for (const [active, label] of [['none', STR['mg-none']], ['custom', STR['mg-custom']]]) {
    const s = BASE(); s.mango.active = active; const y = await boot(s); await y.ready();
    check(y.q('#mg-state').textContent === STR['mg-state'] + ' ' + label && !y.q('.profile.on'), 'estado «' + active + '»');
  }
  let s = BASE(); s.mango.installed = false; x = await boot(s); await x.ready();
  check(x.qa('#content .card')[1].textContent === STR['mg-missing'] && x.qa('[data-profile]').length === 0, 'sin MangoHud: aviso y sin perfiles');
  x = await boot(BASE(), { mango_apply: async () => ({ error: 'write' }) }); await x.ready();
  x.q('[data-profile="minimal"] button').click(); await tick();
  check(x.q('#toast').textContent === STR['mg-err'] && x.q('[data-profile="standard"]').classList.contains('on'), 'si no se puede escribir: aviso y nada cambia');
  check(!p.q('#mg-restore-btn'), 'sin respaldo no hay botón de restaurar');
  s = BASE(); s.mango.has_backup = true; s.mango.active = 'standard'; x = await boot(s); await x.ready();
  check(!!x.q('#mg-restore-btn') && x.q('.note').textContent.length > 0, 'con respaldo aparece restaurar');
  x.q('#mg-restore-btn').click(); await tick(); await tick();
  check(JSON.stringify(x.calls.at(-1)) !== undefined && x.calls.some((c) => c[0] === 'mango_restore') && x.q('#mg-state').textContent.includes(STR['mg-custom']), 'restaurar: llama a la API y muestra tu configuración');

  // ── opciones de lanzamiento ─────────────────────────────────────────────
  x = await boot(BASE()); await x.ready();
  check(x.qa('#lo-profile option').length === 4 && x.q('#lo-profile').value === 'standard', 'selector de perfil con el activo');
  check(x.qa('[data-variant]').length === 4 && x.q('[data-variant="both"] code').textContent === 'mangohud gamemoderun %command%', '4 opciones con su texto');
  x.q('#lo-profile').value = 'hidden'; x.q('#lo-profile').dispatchEvent(new x.w.Event('change')); await tick(); await tick();
  check(x.calls.some((c) => c[0] === 'launch_options' && c[1] === 'hidden') && x.q('[data-variant="profile"] code').textContent.includes('PROFILE-hidden') && x.q('#lo-profile').value === 'hidden', 'cambiar el perfil rehace las opciones');
  x.q('[data-variant="gamemode"] button').click(); await tick();
  check(JSON.stringify(x.calls.at(-1)) === '["copy_options","gamemode","hidden"]' && x.q('#toast').textContent === STR['lo-copied'], 'copiar: variante y perfil correctos y aviso');
  y = await boot(BASE(), { copy_options: async () => ({ ok: false, text: 'x' }) }); await y.ready();
  y.q('[data-variant="both"] button').click(); await tick();
  check(y.q('#toast').textContent === STR['lo-copy-failed'], 'si no hay portapapeles: aviso para copiar a mano');
  s = BASE(); s.mango.active = 'custom'; y = await boot(s); await y.ready();
  check(y.q('#lo-profile').value === 'standard', 'con config propia el selector arranca en Estándar');

  // ── Proton ──────────────────────────────────────────────────────────────
  check(p.qa('#content .card')[3].textContent.includes(STR['pt-none']), 'sin herramientas: aviso');
  s = BASE(); s.tools = ['GE-Proton9-20', 'Proton 9.0', '<img src=x onerror=alert(1)>']; y = await boot(s); await y.ready();
  check(y.qa('.chip').length === 3 && y.qa('img').length === 0 && y.q('.chip:last-child').textContent.startsWith('<img'), 'herramientas como texto, nunca como HTML');
  check(y.qa('#content .card')[3].textContent.includes(STR['pt-count'].replace('{n}', '3')), 'conteo de herramientas');

  // ── gráficos y pantallas ────────────────────────────────────────────────
  const sysTxt = () => p.qa('#content .card')[4].textContent;
  check(sysTxt().includes('AMD · amdgpu') && sysTxt().includes('2560×1440 @ 165 Hz') && sysTxt().includes(STR['sy-vrr-on']), 'GPU y pantalla con VRR');
  s = BASE(); s.system = { gpus: [], monitors: [{ name: 'eDP-1', mode: '1920×1080 @ 60 Hz', vrr: false }, { name: 'HDMI-A-1', mode: '', vrr: null }] };
  y = await boot(s); await y.ready();
  check(y.qa('#content .card')[4].textContent.includes(STR['sy-vrr-off']) && y.qa('#content .card')[4].textContent.includes(STR['sy-none']), 'VRR apagado y GPU sin datos');
  s = BASE(); s.system = { gpus: [], monitors: [] }; y = await boot(s); await y.ready();
  check(y.qa('#content .card')[4].textContent.split(STR['sy-none']).length === 3, 'sin pantallas ni GPU: avisos');

  // ── teclado y errores ───────────────────────────────────────────────────
  p.d.dispatchEvent(new p.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await tick();
  check(JSON.stringify(p.calls.at(-1)) === '["close"]', 'Escape cierra la ventana');
  p.q('#b-close').click(); await tick();
  check(JSON.stringify(p.calls.at(-1)) === '["close"]', 'botón Cerrar');
  x = await boot(BASE(), { snapshot: async () => { throw new Error('boom'); } }); await x.ready();
  check(!x.q('#loading').classList.contains('hidden'), 'si no se puede leer el sistema: sigue el mensaje, sin romper');
  for (const pg of [p, q2, x, y]) check(pg.errors.length === 0, 'sin errores de JavaScript');
  console.log('TODO OK (' + n + ' comprobaciones, ' + lang + ')');
  process.exit(0);
})().catch((e) => { console.log('EXCEPCIÓN: ' + (e && e.stack || e)); process.exit(1); });
