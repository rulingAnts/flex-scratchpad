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
    window.__fsMediaFiles = available;   // the carousel below reads the same list

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

// The hero carousel: the loop video and one picture per feature (Seth, 2026-10-20: "one scrolling
// carousel of screenshots and the video all where the video is now, auto scrolling and also easy for
// people to navigate"). Slides whose picture is not on the manifest are dropped. It advances on its
// own — the video slide for data-hold ms, a picture for 6 s — but not while the pointer or the
// keyboard focus is on it, not while the tab is hidden, and not at all for visitors who ask for
// reduced motion; arrows, dots, ← →, Home / End and a swipe move it by hand.
(function () {
    var car = document.getElementById('hero-carousel');
    if (!car) return;
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var track = car.querySelector('.car-track');
    var dots = car.querySelector('.car-dots');
    var files = window.__fsMediaFiles || Promise.resolve([]);
    files.then(function (list) {
        Array.prototype.slice.call(track.querySelectorAll('.car-slide.still')).forEach(function (sl) {
            var slot = sl.querySelector('.media-slot');
            var img = (slot && slot.getAttribute('data-img')) || '';
            if (list.indexOf(img.split('/').pop()) === -1) sl.parentNode.removeChild(sl);
        });
        var slides = Array.prototype.slice.call(track.children);
        if (slides.length < 2) { car.querySelectorAll('.car-btn, .car-dots').forEach(function (b) { b.hidden = true; }); return; }
        var caption = car.querySelector('.car-caption');
        var count = document.createElement('span'); count.className = 'car-count'; car.appendChild(count);
        var i = 0, timer = null, hold = false;
        slides.forEach(function (sl, k) {
            var d = document.createElement('button'); d.type = 'button'; d.className = 'car-dot'; d.setAttribute('role', 'tab');
            d.setAttribute('aria-label', 'Picture ' + (k + 1) + ' of ' + slides.length);
            d.addEventListener('click', function () { go(k, true); });
            dots.appendChild(d);
        });
        function videoOf(sl) { return sl.querySelector('video'); }
        function go(n, byHand) {
            i = (n + slides.length) % slides.length;
            track.style.transform = 'translateX(-' + (i * 100) + '%)';
            Array.prototype.forEach.call(dots.children, function (d, k) { d.setAttribute('aria-selected', k === i ? 'true' : 'false'); });
            slides.forEach(function (sl, k) {
                sl.setAttribute('aria-hidden', k === i ? 'false' : 'true');
                var v = videoOf(sl);
                if (!v) return;
                if (k === i) { if (!reduce) { var p = v.play(); if (p && p.catch) p.catch(function () {}); } }
                else v.pause();
            });
            if (caption) caption.textContent = slides[i].getAttribute('data-caption') || '';
            count.textContent = (i + 1) + ' / ' + slides.length;
            schedule(byHand);
        }
        function schedule(byHand) {
            if (timer) { clearTimeout(timer); timer = null; }
            if (reduce || hold || document.hidden) return;
            var ms = +(slides[i].getAttribute('data-hold') || 6000);
            if (byHand) ms = Math.max(ms, 9000);                 // a visitor who chose a picture gets to look at it
            timer = setTimeout(function () { go(i + 1); }, ms);
        }
        car.querySelector('.car-btn.prev').addEventListener('click', function () { go(i - 1, true); });
        car.querySelector('.car-btn.next').addEventListener('click', function () { go(i + 1, true); });
        car.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowRight') { e.preventDefault(); go(i + 1, true); }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); go(i - 1, true); }
            else if (e.key === 'Home') { e.preventDefault(); go(0, true); }
            else if (e.key === 'End') { e.preventDefault(); go(slides.length - 1, true); }
        });
        function pause() { hold = true; schedule(); }
        function resume() { hold = false; schedule(); }
        car.addEventListener('mouseenter', pause); car.addEventListener('mouseleave', resume);
        car.addEventListener('focusin', pause); car.addEventListener('focusout', function (e) { if (!car.contains(e.relatedTarget)) resume(); });
        document.addEventListener('visibilitychange', function () { schedule(); });
        var x0 = null;
        car.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; hold = true; }, { passive: true });
        car.addEventListener('touchend', function (e) {
            hold = false;
            if (x0 == null) { schedule(); return; }
            var dx = e.changedTouches[0].clientX - x0; x0 = null;
            if (dx < -40) go(i + 1, true); else if (dx > 40) go(i - 1, true); else schedule();
        }, { passive: true });
        go(0);
    });
})();
