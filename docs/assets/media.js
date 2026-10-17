// FLEx Scratchpad site: media slots (the same script as LingTeX Tools' site).
//
// A slot (<figure class="media-slot" data-video=… or data-img=…>) shows its
// placeholder until its recording is on the site; then this swaps the file in.
// Which files exist is read from ONE list, named by the page's
// <meta name="media-manifest" content="…/available.json">, so a page never asks
// for a file that is not there (a probe per slot would put a 404 in every
// visitor's console until the media arrived). The files and the list are made
// by tools/record_demo.py, which films the real program; no page edit.
//
// Videos play muted and looped, only while on screen, and not at all for
// visitors who ask for reduced motion (they get the controls instead).
(function () {
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var meta = document.querySelector('meta[name="media-manifest"]');
    var available = (!meta || !window.fetch || location.protocol === 'file:')
        ? Promise.resolve([])
        : fetch(meta.getAttribute('content'), { cache: 'no-cache' })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .then(function (j) { return (j && j.files) || []; })
            .catch(function () { return []; });

    // A slot's file is available when its name is on the list.
    function exists(url) {
        var name = url.split('/').pop();
        return available.then(function (files) { return files.indexOf(name) !== -1; });
    }

    var watcher = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
            var v = e.target;
            if (e.isIntersecting) { var p = v.play(); if (p && p.catch) p.catch(function () { v.controls = true; }); }
            else { v.pause(); }
        });
    }, { threshold: 0.25 }) : null;

    document.querySelectorAll('.media-slot').forEach(function (slot) {
        var label = slot.getAttribute('data-label') || '';
        var video = slot.getAttribute('data-video');
        var img = slot.getAttribute('data-img');
        if (video) {
            var poster = slot.getAttribute('data-poster');
            var webm = slot.getAttribute('data-webm');
            // The poster and the WebM are optional: each is used only when it,
            // too, is on the list, so a slot never requests a file not there.
            Promise.all([exists(video), poster ? exists(poster) : false, webm ? exists(webm) : false]).then(function (have) {
                if (!have[0]) return;
                var v = document.createElement('video');
                v.muted = true; v.defaultMuted = true; v.loop = true; v.playsInline = true;
                v.setAttribute('muted', ''); v.setAttribute('playsinline', '');
                v.preload = 'metadata';
                v.setAttribute('aria-label', label);
                if (have[1]) v.poster = poster;
                if (have[2]) { var s1 = document.createElement('source'); s1.src = webm; s1.type = 'video/webm'; v.appendChild(s1); }
                var s2 = document.createElement('source'); s2.src = video; s2.type = 'video/mp4'; v.appendChild(s2);
                slot.appendChild(v);
                slot.classList.add('has-media');
                if (reduce) { v.controls = true; }
                else if (watcher) { watcher.observe(v); }
                else { v.autoplay = true; }
            });
        } else if (img) {
            exists(img).then(function (ok) {
                if (!ok) return;
                var i = new Image();
                i.alt = label; i.loading = 'lazy'; i.decoding = 'async'; i.src = img;
                slot.appendChild(i);
                slot.classList.add('has-media');
            });
        }
    });
})();
