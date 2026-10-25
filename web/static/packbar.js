/* WrenchAtlas · 车型包上下文
 *
 * 作用：让每个页面都知道"当前在看哪款车"，并提供带 pack 参数的链接。
 *
 * 优先级：URL ?pack= > localStorage > 服务端默认
 * 为什么用 localStorage：手机上点来点去不想每次都带参数。
 */
(function () {
  var params = new URLSearchParams(location.search);
  var fromUrl = params.get('pack');
  var cur = fromUrl || localStorage.getItem('wa_pack') || '';
  if (fromUrl) localStorage.setItem('wa_pack', fromUrl);

  var WA = window.WA = window.WA || {};

  WA.pack = function () { return cur; };

  WA.withPack = function (url) {
    if (!cur) return url;
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'pack=' + encodeURIComponent(cur);
  };

  /* 全站链接统一加 pack：给 <a data-pack> 打标记的才处理 */
  WA.bindLinks = function (root) {
    (root || document).querySelectorAll('a[data-pack]').forEach(function (a) {
      if (a.dataset.packed) return;
      a.href = WA.withPack(a.getAttribute('href'));
      a.dataset.packed = '1';
    });
  };

  /* 渲染车型切换器。只有一个车型包时自动隐藏。 */
  function renderBar(packs) {
    var host = document.getElementById('packbar');
    if (!host) return;
    if (!packs || packs.length < 2) return;

    var curId = cur || (packs.find(function (p) { return p.is_default; }) || packs[0]).id;
    var sel = document.createElement('select');
    sel.setAttribute('aria-label', '切换车型');
    sel.style.cssText = 'font:inherit;font-size:12.5px;padding:6px 10px;border-radius:8px;' +
      'border:1px solid var(--line,#3a3a3a);background:var(--panel,#1b1d21);' +
      'color:var(--fg,#e8e6e1);max-width:min(56vw,280px)';
    packs.forEach(function (p) {
      var o = document.createElement('option');
      o.value = p.id;
      o.textContent = (p.label || p.id) + (p.pages ? '' : ' · 空包');
      if (p.id === curId) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = function () {
      localStorage.setItem('wa_pack', sel.value);
      var u = new URL(location.href);
      u.searchParams.set('pack', sel.value);
      location.href = u.toString();
    };
    host.appendChild(sel);
    host.style.display = '';
  }

  document.addEventListener('DOMContentLoaded', function () {
    WA.bindLinks();
    fetch('/api/packs').then(function (r) { return r.json(); })
      .then(function (d) { renderBar(d.packs); })
      .catch(function () { });
  });
})();
