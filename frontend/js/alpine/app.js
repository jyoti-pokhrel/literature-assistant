document.addEventListener('alpine:init', () => {
    Alpine.data('appShell', () => ({
        init() {
            this.$store.app.init();
            this.setupRevealObserver();
            this.setupGlassGlow();
            this.setupNavScroll();
        },

        /* Scroll-reveal — fades + lifts elements as they enter viewport.
           Adds .is-in-view (and .visible for backwards-compat with .fade-in).
           Robust against fast scrolls + above-the-fold elements: any element
           already in or above the viewport at observer setup is revealed
           immediately. */
        setupRevealObserver() {
            const targets = document.querySelectorAll('.fade-in');
            if (!targets.length || typeof IntersectionObserver === 'undefined') {
                targets.forEach((el) => el.classList.add('is-in-view', 'visible'));
                return;
            }
            const reveal = (el) => el.classList.add('is-in-view', 'visible');

            // Pre-pass: any element already touching the viewport gets revealed now.
            const vh = window.innerHeight;
            targets.forEach((el) => {
                const rect = el.getBoundingClientRect();
                if (rect.top < vh * 1.1) reveal(el);
            });

            const observer = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        reveal(entry.target);
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0, rootMargin: '0px 0px -10% 0px' });
            targets.forEach((el) => {
                if (!el.classList.contains('is-in-view')) observer.observe(el);
            });

            // Belt-and-braces fallback: anything still hidden after 1.5s gets revealed
            // (e.g., headless browser screenshots, instant programmatic scrolls).
            setTimeout(() => {
                document.querySelectorAll('.fade-in:not(.is-in-view)').forEach(reveal);
            }, 1500);
        },

        /* Cursor-follow glow — sets --cursor-x / --cursor-y on .glass-glow
           surfaces while the pointer is over them. CSS uses these in a
           radial-gradient to render a soft highlight that tracks the pointer. */
        setupGlassGlow() {
            const handle = (event) => {
                const el = event.currentTarget;
                const rect = el.getBoundingClientRect();
                const x = ((event.clientX - rect.left) / rect.width) * 100;
                const y = ((event.clientY - rect.top) / rect.height) * 100;
                el.style.setProperty('--cursor-x', x + '%');
                el.style.setProperty('--cursor-y', y + '%');
            };

            const bind = (root = document) => {
                root.querySelectorAll('.glass-glow').forEach((el) => {
                    if (el.dataset.glowBound) return;
                    el.dataset.glowBound = '1';
                    el.addEventListener('pointermove', handle);
                });
            };
            bind();

            // Re-bind when Alpine swaps DOM (results page enters)
            const mo = new MutationObserver(() => bind());
            mo.observe(document.body, { childList: true, subtree: true });
        },

        /* Nav — adds .is-scrolled when the user has scrolled past the hero. */
        setupNavScroll() {
            const nav = document.getElementById('lp-nav');
            if (!nav) return;
            const onScroll = () => {
                if (window.scrollY > 24) nav.classList.add('is-scrolled');
                else nav.classList.remove('is-scrolled');
            };
            onScroll();
            window.addEventListener('scroll', onScroll, { passive: true });
        },
    }));
});
