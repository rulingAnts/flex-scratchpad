// FLEx Scratchpad site: point the download links at the current release, and at the pre-release
// that is newer than it (Seth, 2026-10-20: "the buttons should offer both").
//
// The links in the page are written for the releases that were current when it was edited; this
// asks GitHub for the newest RELEASE (not marked pre-release) that carries BOTH downloads — the
// Setup .exe and the portable zip — and for the newest PRE-release published after it with both
// files, and moves every link and version text to them together, so the page never names one
// version and downloads another. A release with missing files is skipped for the next older one
// (LingTeX Tools learnt that the hard way: a release can exist with its files deleted). When no
// full release exists the newest pre-release stands in for it; when no pre-release is newer than
// the release, the elements marked data-pre are hidden. Anything that fails leaves the written
// links. Elements carry data-dl="exe" | "zip" | "notes" (href) or "version" (text), and
// "pre-exe" | "pre-zip" | "pre-notes" | "pre-version" for the pre-release.
//
// pickReleases() is the choice alone, without the page, so it can be tested in node.
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
  function pickReleases(list) {
    if (!Array.isArray(list)) return null;
    var rels = list.filter(function (r) { return r && typeof r.published_at === 'string'; })
      .sort(function (a, b) { return a.published_at < b.published_at ? 1 : -1; });   // newest first
    var release = null, pre = null, i, l;
    for (i = 0; i < rels.length && !release; i++) { if (!rels[i].prerelease) { l = linksOf(rels[i]); if (l) release = { links: l, at: rels[i].published_at }; } }
    if (!release) { for (i = 0; i < rels.length && !release; i++) { l = linksOf(rels[i]); if (l) release = { links: l, at: rels[i].published_at }; } }
    if (!release) return null;
    for (i = 0; i < rels.length && !pre; i++) {
      if (rels[i].prerelease && rels[i].published_at > release.at) { l = linksOf(rels[i]); if (l) pre = l; }
    }
    return { release: release.links, pre: pre };
  }
  function pickRelease(list) { var r = pickReleases(list); return r ? r.release : null; }
  if (typeof module !== 'undefined') module.exports = { pickRelease: pickRelease, pickReleases: pickReleases };
  if (typeof document === 'undefined' || !window.fetch || location.protocol === 'file:') return;
  fetch('https://api.github.com/repos/rulingAnts/flex-scratchpad/releases?per_page=20', { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (list) {
      var r = pickReleases(list);
      if (!r) return;
      function apply(l, prefix) {
        document.querySelectorAll('[data-dl]').forEach(function (el) {
          var k = el.getAttribute('data-dl');
          if (k.indexOf(prefix) !== 0 || (!prefix && k.indexOf('pre-') === 0)) return;
          k = k.slice(prefix.length);
          if (k === 'version') el.textContent = l.version;
          else if (l[k]) el.setAttribute('href', l[k]);
        });
      }
      apply(r.release, '');
      if (r.pre) apply(r.pre, 'pre-');
      else document.querySelectorAll('[data-pre]').forEach(function (el) { el.hidden = true; });
    })
    .catch(function () { /* the written links stay */ });
})();
