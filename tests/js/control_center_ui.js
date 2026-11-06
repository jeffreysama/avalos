// Prueba de humo del front-end de avalos-control con jsdom (sin navegador).
//   node control_center_ui.js <pagina.html> <idioma>      (jsdom en NODE_PATH)
// Imprime una línea "ok: ..." por comprobación y sale con 1 en la primera que falle.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const [, , file, lang] = process.argv;
const html = fs.readFileSync(file, 'utf8');
const STR = JSON.parse(/const S = (\{.*?\});\nconst TILES/s.exec(html)[1]);

const calls = [];
const state = { avail: {}, health: { state: 'error' }, info: { os: 'AvalOS', kernel: '6.x', cpu: 'CPU', memory: '1 / 2 GiB', disk: '3 / 4 GiB (75%)', uptime: '5m' }, opened: true };
const errors = [];

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  beforeParse(window) {
    window.addEventListener('error', (e) => errors.push(String(e.error || e.message)));
    window.pywebview = { api: {
      info: async () => state.info,
      available: async () => state.avail,
      open_tile: async (id) => { calls.push(['open_tile', id]); return state.opened; },
      health: async () => { calls.push(['health']); return state.health; },
      close: async () => { calls.push(['close']); },
    } };
  },
});
const { window } = dom;
const doc = window.document;
const tick = () => new Promise((r) => setTimeout(r, 20));
const q = (sel) => doc.querySelector(sel);
const qa = (sel) => Array.from(doc.querySelectorAll(sel));
let n = 0;
function check(cond, what) { n++; if (!cond) { console.log('FALLA: ' + what); process.exit(1); } console.log('ok: ' + what); }
const key = (target, k) => target.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
const type = (text) => { const s = q('#search'); s.value = text; s.dispatchEvent(new window.Event('input', { bubbles: true })); };

(async () => {
  check(doc.documentElement.lang === (lang === 'zh' ? 'zh-CN' : lang), 'lang del documento');
  check(q('#title').textContent === STR.title, 'título');
  check(q('.accent') === null || q('.accent').textContent === 'AvalOS', 'AvalOS con degradado en el título');
  check(qa('.tile').length === 15, '15 lanzadores dibujados');
  check(qa('#groups h2').length === 5, '5 grupos');
  check(qa('.fact').length === 6 && qa('.fact .v').every((v) => v.textContent === '—'), 'resumen con «—» antes de cargar');

  // la ventana ya dibujada: datos reales y lanzadores no instalados
  state.avail = { doctor: false, nm: true };
  window.dispatchEvent(new window.Event('pywebviewready'));
  await tick();
  check(qa('.fact .v').map((v) => v.textContent).join('|') === 'AvalOS|6.x|CPU|1 / 2 GiB|3 / 4 GiB (75%)|5m', 'resumen del equipo cargado');
  const doctor = q('[data-tile="doctor"]');
  check(doctor.disabled && doctor.querySelector('.d').textContent === STR.unavailable, 'lanzador no instalado: desactivado y con aviso');
  check(!q('[data-tile="update"]').disabled, 'los demás siguen activos');

  // clic
  q('[data-tile="update"]').click(); await tick();
  check(JSON.stringify(calls.at(-1)) === '["open_tile","update"]', 'clic abre el lanzador correcto');
  state.opened = false; q('[data-tile="store"]').click(); await tick();
  check(!q('#toast').classList.contains('hidden') && q('#toast').textContent === STR.unavailable, 'si no se puede abrir: aviso');
  state.opened = true;

  // búsqueda
  type('wi-fi');
  check(qa('.tile').length === 1 && q('.tile').dataset.tile === 'network', 'buscar «wi-fi» deja solo Red');
  check(q('#overview').classList.contains('hidden'), 'al buscar se oculta el resumen');
  check(qa('#groups h2').length === 1, 'al buscar solo queda el grupo con resultados');
  type('zzzz-nada');
  check(qa('.tile').length === 0 && !q('#empty').classList.contains('hidden') && q('#empty').textContent.includes('zzzz-nada'), 'sin resultados: mensaje con lo buscado');
  type('<img src=x onerror=alert(1)>');
  check(qa('img').length === 0 && q('#empty').textContent.includes('<img'), 'lo buscado se muestra como texto, nunca como HTML');
  type('');
  check(qa('.tile').length === 15 && !q('#overview').classList.contains('hidden'), 'vaciar la búsqueda lo restaura todo');

  // Enter abre el primer resultado activo (el Doctor está desactivado, así que no cuenta)
  type('health'); calls.length = 0;
  key(q('#search'), 'Enter'); await tick();
  const first = calls.at(-1);
  check(!first || first[1] !== 'doctor', 'Enter no abre un lanzador desactivado');
  type('wallpaper'); calls.length = 0; key(q('#search'), 'Enter'); await tick();
  check(JSON.stringify(calls.at(-1)) === '["open_tile","wallpaper"]', 'Enter abre el primer resultado activo');
  type('');

  // teclado
  doc.activeElement.blur && doc.activeElement.blur();
  key(doc, '/'); check(doc.activeElement === q('#search'), '«/» enfoca la búsqueda');
  type('red'); calls.length = 0;
  key(doc, 'Escape'); check(q('#search').value === '' && calls.length === 0, 'Escape con búsqueda: la borra y no cierra');
  key(doc, 'Escape'); await tick(); check(JSON.stringify(calls.at(-1)) === '["close"]', 'Escape sin búsqueda: cierra la ventana');

  // salud
  state.health = { state: 'done', ok: 12, warn: 1, fail: 1, issues: [{ title: '<b>Disco</b> casi lleno', status: 'fail' }, { title: 'Mirrors lentos', status: 'warn' }] };
  q('#health-btn').click(); check(q('#health-btn').disabled && q('#health-btn').textContent === STR['health-running'], 'salud: botón en «Revisando…»');
  await tick();
  const sum = STR['health-summary'].replace('{ok}', 12).replace('{warn}', 1).replace('{fail}', 1);
  check(q('#health-res .sum').textContent === sum, 'salud: resumen con los conteos');
  check(qa('#health-res li').length === 2 && qa('#health-res li .dot.fail').length === 1 && qa('#health-res b').length === 1, 'salud: problemas listados, su HTML no se interpreta');
  check(q('#health-btn').textContent === STR['health-again'] && !q('#health-btn').disabled, 'salud: botón pasa a «Revisar de nuevo»');
  calls.length = 0; qa('#health-res .btn')[0].click(); await tick();
  check(JSON.stringify(calls.at(-1)) === '["open_tile","doctor"]', 'salud: abre el Doctor');
  state.health = { state: 'done', ok: 20, warn: 0, fail: 0, issues: [] };
  q('#health-btn').click(); await tick();
  check(q('#health-res .clean').textContent === STR['health-clean'] && qa('#health-res li').length === 0, 'salud limpia: mensaje y sin lista');
  state.health = { state: 'error' }; q('#health-btn').click(); await tick();
  check(q('#health-res').textContent === STR['health-err'] && !q('#health-btn').disabled, 'Doctor falla: aviso y el botón vuelve a estar activo');
  state.health = { state: 'missing' }; q('#health-btn').click(); await tick();
  check(q('#health-res').textContent === STR['health-na'] && q('#health-btn').disabled, 'Doctor no instalado: aviso y botón desactivado');
  check(errors.length === 0, 'sin errores de JavaScript');
  console.log('TODO OK (' + n + ' comprobaciones, ' + lang + ')');
  process.exit(0);
})().catch((e) => { console.log('EXCEPCIÓN: ' + (e && e.stack || e)); process.exit(1); });
