// FLEx Scratchpad site: point the download links at the newest release that has its files.
//
// The links in the page are written for the release that was current when it was edited; this
// asks GitHub for the newest one (a pre-release counts: there is no other kind yet) that carries
// BOTH downloads — the Setup .exe and the portable zip — and moves every link and the version
// text to it together, so the page never names one version and downloads another. A release
// with missing files is skipped for the next older one (LingTeX Tools learnt that the hard way:
// a release can exist with its files deleted). Anything that fails leaves the written links.
// Elements carry data-dl="exe" | "zip" | "notes" (href) or "version" (text).
//
// pickRelease() is the choice alone, without the page, so it can be tested in node.
(function () {
  var REPO = 'https://github.com/rulingAnts/flex-scratchpad/releases/';
  var want = {
    exe: function (n) { return /^FLEx-Scratchpad-Setup-.*\.exe$/.test(n); },
    zip: function (n) { return /-windows-portable\.zip$/.test(n); }
  };
  function ours(u) { return typeof u === 'string' && u.indexOf(REPO) === 0; }

  function linksOf(rel) {
    if (!rel || rel.draft || !ours(rel.html_url) || !Array.isArray(rel.assets)) return null;
    var out = { version: String(rel.tag_name || '').replace(/^v/, ''), notes: rel.html_url };
    Object.keys(want).forEach(function (k) {
      rel.assets.forEach(function (a) {
        if (!out[k] && a && typeof a.name === 'string' && want[k](a.name) && ours(a.browser_download_url)) out[k] = a.browser_download_url;
      });
    });
    return out.exe && out.zip ? out : null;
  }
  function pickRelease(list) {
    if (!Array.isArray(list)) return null;
    var rels = list.filter(function (r) { return r && typeof r.published_at === 'string'; })
      .sort(function (a, b) { return a.published_at < b.published_at ? 1 : -1; });   // newest first
    for (var i = 0; i < rels.length; i++) { var l = linksOf(rels[i]); if (l) return l; }
    return null;
  }
  if (typeof module !== 'undefined') module.exports = { pickRelease: pickRelease };
  if (typeof document === 'undefined' || !window.fetch || location.protocol === 'file:') return;
  fetch('https://api.github.com/repos/rulingAnts/flex-scratchpad/releases?per_page=20', { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (list) {
      var l = pickRelease(list);
      if (!l) return;
      document.querySelectorAll('[data-dl]').forEach(function (el) {
        var k = el.getAttribute('data-dl');
        if (k === 'version') el.textContent = l.version;
        else if (l[k]) el.setAttribute('href', l[k]);
      });
    })
    .catch(function () { /* the written links stay */ });
})();
