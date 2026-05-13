/**
 * CitationGraph — Connected-Papers-style citation network.
 *
 * Design vocabulary (matches the app's existing cluster map):
 *   - Theme-driven: reads --ink, --ink-2, --ink-3, --c-1..4, --rule* from tokens.css.
 *   - Glass canvas, no custom dark backdrop — inherits the surrounding card.
 *   - Node fill encodes YEAR on a sequential ramp (older → lighter, newer → darker).
 *   - Node radius encodes log(citation_count).
 *   - Seed = ink fill + accent ring, slightly larger, distinct from the year-grey field.
 *   - References = solid disc. Citers = outlined ring (hollow center).
 *   - Force layout biases refs LEFT of seed, citers RIGHT — past→future axis emerges.
 *   - Edges: subtle straight gray lines, no arrowheads. Hover highlights adjacents.
 *   - Hover-only Gaussian glow on the focused node. No pulses, no flashing.
 *
 * Public surface (unchanged from prior versions):
 *   window.CitationGraph = {
 *     render(selector, data, callbacks),
 *     replaceData(data),
 *     merge(addedNodes, addedEdges),
 *     filter({ showRefs, showCiters, minCites, yearRange }),
 *     highlight(nodeId),
 *     zoomBy(factor), zoomReset(),
 *     applyTheme(),
 *     destroy(),
 *   }
 */
(function () {
    'use strict';

    let state = null;

    // ---------- palette (read from CSS tokens, re-read on theme:change) ----------

    function readPalette() {
        const cs = getComputedStyle(document.documentElement);
        const get = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            isDark,
            // Sequential year ramp: c4 (lightest) → c1 (darkest ink).
            // tokens.css inverts these per theme, so the ramp self-flips.
            rampA: get('--c-4', '#c0c7d3'),
            rampB: get('--c-3', '#8b95a4'),
            rampC: get('--c-2', '#4a5564'),
            rampD: get('--c-1', '#1a1816'),
            ink:    get('--ink',   '#050608'),
            ink2:   get('--ink-2', '#4a5564'),
            ink3:   get('--ink-3', '#8b95a4'),
            rule:   get('--rule',        'rgba(5,6,8,0.07)'),
            ruleStrong: get('--rule-strong', 'rgba(5,6,8,0.14)'),
            paper:  get('--bg',    '#f5f7fa'),
            paper2: get('--bg-2',  '#eceff5'),
            accent: get('--accent','#050608'),
            // One warm hue, used ONLY to set the seed apart. Tuned to read on
            // both light and dark glass without screaming.
            seedAccent: isDark ? '#f4c47a' : '#b86b3c',
        };
    }

    // ---------- helpers ----------

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function truncate(s, n) {
        const v = String(s || '');
        return v.length > n ? v.slice(0, n - 1) + '…' : v;
    }

    function radiusFor(node) {
        const cc = Math.max(0, Number(node.citation_count) || 0);
        const r = 5 + 2.6 * Math.log(1 + cc);
        const base = Math.max(5, Math.min(22, r));
        return node.role === 'seed' ? Math.max(base, 11) : base;
    }

    function computeYearExtent(nodes) {
        let lo = Infinity, hi = -Infinity, seen = 0;
        for (const n of nodes) {
            const y = Number(n.year);
            if (!Number.isFinite(y) || y < 1500 || y > 2100) continue;
            seen += 1;
            if (y < lo) lo = y;
            if (y > hi) hi = y;
        }
        if (!seen) {
            const now = new Date().getFullYear();
            return [now - 20, now];
        }
        if (lo === hi) return [lo - 1, hi + 1];
        return [lo, hi];
    }

    function makeYearScale(extent, palette) {
        return d3.scaleLinear()
            .domain([extent[0], (extent[0] + extent[1]) / 2, extent[1]])
            .range([palette.rampA, palette.rampB, palette.rampD])
            .interpolate(d3.interpolateLab)
            .clamp(true);
    }

    function nodeFill(d, scale, palette) {
        if (d.role === 'seed') return palette.ink;
        if (d.role === 'citer') return 'transparent'; // outlined ring
        const y = Number(d.year);
        if (!Number.isFinite(y)) return palette.rampB;
        return scale(y);
    }

    function nodeStroke(d, scale, palette) {
        if (d.role === 'seed') return palette.seedAccent;
        const y = Number(d.year);
        const base = Number.isFinite(y) ? scale(y) : palette.rampC;
        return base;
    }

    function nodeStrokeWidth(d) {
        if (d.role === 'seed') return 2.2;
        if (d.role === 'citer') return 1.8;
        return 0.9;
    }

    // ---------- defs ----------

    function buildDefs(defs, palette) {
        defs.selectAll('*').remove();

        // Soft glow filter — applied only on hovered/highlighted nodes.
        const glow = defs.append('filter')
            .attr('id', 'cit-glow')
            .attr('x', '-50%').attr('y', '-50%')
            .attr('width', '200%').attr('height', '200%');
        glow.append('feGaussianBlur').attr('stdDeviation', 2.6).attr('result', 'b');
        const m = glow.append('feMerge');
        m.append('feMergeNode').attr('in', 'b');
        m.append('feMergeNode').attr('in', 'SourceGraphic');
    }

    // ---------- tooltip ----------

    function ensureTooltip() {
        return d3.select(document.body)
            .append('div')
            .attr('class', 'cit-graph-tooltip')
            .style('position', 'absolute')
            .style('pointer-events', 'none')
            .style('opacity', 0)
            .style('z-index', 1100)
            .style('background', 'var(--glass-strong, var(--glass))')
            .style('backdrop-filter', 'var(--glass-blur)')
            .style('-webkit-backdrop-filter', 'var(--glass-blur)')
            .style('border', '1px solid var(--glass-border)')
            .style('border-radius', '12px')
            .style('padding', '10px 13px')
            .style('color', 'var(--ink)')
            .style('max-width', '320px')
            .style('font-size', '0.78rem')
            .style('line-height', '1.45')
            .style('box-shadow', 'var(--shadow-glass)')
            .style('transition', 'opacity 0.16s cubic-bezier(0.22,1,0.36,1)');
    }

    function roleLabel(role) {
        if (role === 'seed') return 'Seed';
        if (role === 'citer') return 'Citer';
        return 'Reference';
    }

    function tooltipHtml(node, palette) {
        const title = escapeHtml(truncate(node.title, 90));
        const authors = Array.isArray(node.authors) ? node.authors.slice(0, 3) : [];
        const authorLabel = authors.length
            ? escapeHtml(authors.join(', ')) + (node.authors && node.authors.length > 3 ? ' et al.' : '')
            : '<span style="opacity:0.55">Authors unknown</span>';
        const cc = Number.isFinite(node.citation_count)
            ? `${node.citation_count.toLocaleString()} citations` : '';
        const year = node.year || '—';
        const dot = node.role === 'seed' ? palette.seedAccent
                  : node.role === 'citer' ? 'transparent'
                  : palette.rampC;
        const border = node.role === 'citer' ? `1.5px solid ${palette.ink2}` : '0';
        return `
            <div style="font-weight:600; margin-bottom:5px;">${title}</div>
            <div style="font-size:0.72rem; color:var(--ink-2);">${authorLabel}</div>
            <div style="font-size:0.7rem; margin-top:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; color:var(--ink-2);">
                <span style="display:inline-flex; align-items:center; gap:5px;">
                  <span style="width:8px; height:8px; border-radius:50%; background:${dot}; border:${border}; box-sizing:border-box;"></span>
                  ${roleLabel(node.role)}
                </span>
                <span style="opacity:0.4;">·</span>
                <span>${year}</span>
                ${cc ? `<span style="opacity:0.4;">·</span><span>${cc}</span>` : ''}
            </div>
        `;
    }

    // ---------- filtering ----------

    function visibleNodeIds(data, filters) {
        const { showRefs, showCiters, minCites, yearRange } = filters;
        const [minYear, maxYear] = yearRange || [-Infinity, Infinity];
        const visible = new Set();
        for (const node of data.nodes) {
            if (node.role === 'seed') { visible.add(node.id); continue; }
            if (node.role === 'reference' && !showRefs) continue;
            if (node.role === 'citer' && !showCiters) continue;
            const cc = Number(node.citation_count) || 0;
            if (cc < (minCites || 0)) continue;
            const y = Number(node.year);
            if (Number.isFinite(y) && (y < minYear || y > maxYear)) continue;
            visible.add(node.id);
        }
        return visible;
    }

    // ---------- render ----------

    function renderImpl() {
        if (!state) return;
        const { container, data, callbacks, filters } = state;

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 620;
        state.width = width;
        state.height = height;

        state.svg
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', `0 0 ${width} ${height}`);

        const visible = visibleNodeIds(data, filters);
        const renderNodes = data.nodes.filter((n) => visible.has(n.id));
        const renderEdges = data.edges
            .filter((e) => {
                const sid = typeof e.source === 'object' ? e.source.id : e.source;
                const tid = typeof e.target === 'object' ? e.target.id : e.target;
                return visible.has(sid) && visible.has(tid);
            })
            .map((e) => ({ ...e }));

        // Year scale (recomputed each render so it adapts to filtered set).
        const yearExtent = computeYearExtent(renderNodes);
        const yearScale = makeYearScale(yearExtent, state.palette);
        state.yearExtent = yearExtent;
        state.yearScale = yearScale;
        if (typeof state.onLegendUpdate === 'function') {
            state.onLegendUpdate(yearExtent, yearScale, state.palette);
        }

        // ---- edges ----
        const edgeKey = (d) => {
            const sid = typeof d.source === 'object' ? d.source.id : d.source;
            const tid = typeof d.target === 'object' ? d.target.id : d.target;
            return `${sid}->${tid}:${d.kind}`;
        };

        const edgeSel = state.linkGroup.selectAll('line.cit-edge')
            .data(renderEdges, edgeKey);

        edgeSel.exit().remove();

        const edgeEnter = edgeSel.enter()
            .append('line')
            .attr('class', 'cit-edge')
            .attr('stroke-linecap', 'round')
            .attr('stroke', state.palette.ink3)
            .attr('stroke-width', 0.8)
            .attr('stroke-opacity', 0);

        edgeEnter.transition().duration(520).delay(220)
            .attr('stroke-opacity', 0.22);

        const edgeMerged = edgeEnter.merge(edgeSel)
            .attr('stroke', state.palette.ink3);

        // ---- nodes ----
        const nodeSel = state.nodeGroup.selectAll('g.cit-node')
            .data(renderNodes, (d) => d.id);

        nodeSel.exit().remove();

        const nodeEnter = nodeSel.enter()
            .append('g')
            .attr('class', (d) => `cit-node cit-node--${d.role || 'reference'}`)
            .style('cursor', 'pointer')
            .attr('opacity', 0)
            .call(state.drag);

        nodeEnter.transition()
            .duration(460)
            .delay((d, i) => Math.min(i * 5, 700))
            .attr('opacity', 1);

        // visible disc / ring
        nodeEnter.append('circle')
            .attr('class', 'cit-core')
            .attr('r', (d) => radiusFor(d))
            .attr('fill', (d) => nodeFill(d, yearScale, state.palette))
            .attr('stroke', (d) => nodeStroke(d, yearScale, state.palette))
            .attr('stroke-width', (d) => nodeStrokeWidth(d))
            .attr('pointer-events', 'none');

        // seed accent halo ring (subtle, no animation)
        nodeEnter.filter((d) => d.role === 'seed')
            .append('circle')
            .attr('class', 'cit-seed-halo')
            .attr('r', (d) => radiusFor(d) + 5)
            .attr('fill', 'none')
            .attr('stroke', state.palette.seedAccent)
            .attr('stroke-width', 0.8)
            .attr('stroke-opacity', 0.45)
            .attr('pointer-events', 'none');

        // hit target — captures pointer over a slightly larger area
        nodeEnter.append('circle')
            .attr('class', 'cit-hit')
            .attr('r', (d) => Math.max(14, radiusFor(d) + 6))
            .attr('fill', 'transparent')
            .attr('pointer-events', 'all')
            .on('mouseenter', function (event, d) {
                state.tooltip.html(tooltipHtml(d, state.palette)).style('opacity', 1);
                focusNode(d.id, /*persistent*/ false);
            })
            .on('mousemove', function (event) {
                // Boundary-aware placement so the tooltip doesn't escape the viewport.
                const tipEl = state.tooltip.node();
                const tw = tipEl?.offsetWidth || 240;
                const th = tipEl?.offsetHeight || 80;
                const vw = window.innerWidth;
                const vh = window.innerHeight;
                const pad = 14;
                let left = event.pageX + pad;
                let top = event.pageY - pad - th;
                const pageRight = window.scrollX + vw;
                const pageBottom = window.scrollY + vh;
                if (left + tw + 8 > pageRight) left = event.pageX - tw - pad;
                if (top < window.scrollY + 8) top = event.pageY + pad;
                if (top + th + 8 > pageBottom) top = pageBottom - th - 8;
                state.tooltip
                    .style('left', `${Math.max(window.scrollX + 8, left)}px`)
                    .style('top', `${Math.max(window.scrollY + 8, top)}px`);
            })
            .on('mouseleave', function () {
                state.tooltip.style('opacity', 0);
                if (!state.lockedHighlightId) focusNode(null, false);
            })
            .on('click', function (event, d) {
                event.stopPropagation();
                if (event.shiftKey) {
                    d.fx = null; d.fy = null;
                    state.simulation.alpha(0.35).restart();
                    return;
                }
                callbacks?.onSelect?.(d);
                state.dispatch('paper:select', { paper: d });
            })
            .on('dblclick', function (event, d) {
                event.preventDefault();
                event.stopPropagation();
                callbacks?.onExpand?.(d.id, d);
            });

        // update geometry on existing nodes
        const nodeMerged = nodeEnter.merge(nodeSel);
        nodeMerged.select('.cit-core')
            .attr('r', (d) => radiusFor(d))
            .attr('fill', (d) => nodeFill(d, yearScale, state.palette))
            .attr('stroke', (d) => nodeStroke(d, yearScale, state.palette))
            .attr('stroke-width', (d) => nodeStrokeWidth(d));
        nodeMerged.select('.cit-seed-halo')
            .attr('r', (d) => radiusFor(d) + 5);
        nodeMerged.select('.cit-hit')
            .attr('r', (d) => Math.max(14, radiusFor(d) + 6));

        // ---- simulation ----
        state.simulation.nodes(renderNodes);
        state.simulation.force('link')
            .links(renderEdges)
            .distance((d) => {
                const tgt = typeof d.target === 'object' ? d.target : null;
                const cc = tgt ? (Number(tgt.citation_count) || 0) : 0;
                return 70 + 4.5 * Math.log(1 + cc);
            });

        // Past → future axis: refs left, citers right.
        state.simulation.force('x',
            d3.forceX((d) => {
                if (d.role === 'reference') return width * 0.30;
                if (d.role === 'citer')     return width * 0.70;
                return width / 2;
            }).strength(0.07)
        );
        state.simulation.force('center', d3.forceCenter(width / 2, height / 2));

        state.simulation.alpha(0.9).restart();

        const linkAll = state.linkGroup.selectAll('line.cit-edge');
        state.tickFn = function tick() {
            linkAll
                .attr('x1', (d) => d.source.x ?? 0)
                .attr('y1', (d) => d.source.y ?? 0)
                .attr('x2', (d) => d.target.x ?? 0)
                .attr('y2', (d) => d.target.y ?? 0);
            state.nodeGroup.selectAll('g.cit-node')
                .attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
        };
        state.simulation.on('tick', state.tickFn);
    }

    // ---------- highlight ----------

    function adjacencySet(nodeId) {
        const adj = new Set([nodeId]);
        if (!state) return adj;
        for (const e of state.data.edges) {
            const sid = typeof e.source === 'object' ? e.source.id : e.source;
            const tid = typeof e.target === 'object' ? e.target.id : e.target;
            if (sid === nodeId) adj.add(tid);
            if (tid === nodeId) adj.add(sid);
        }
        return adj;
    }

    function focusNode(nodeId, persistent) {
        if (!state) return;
        if (persistent) state.lockedHighlightId = nodeId;

        const nodes = state.nodeGroup.selectAll('g.cit-node');
        const edges = state.linkGroup.selectAll('line.cit-edge');

        if (!nodeId) {
            nodes.classed('is-active', false).classed('is-dim', false);
            nodes.select('.cit-core').attr('filter', null);
            edges.classed('is-active', false)
                .attr('stroke-opacity', 0.22)
                .attr('stroke-width', 0.8);
            return;
        }

        const adj = adjacencySet(nodeId);
        nodes
            .classed('is-active', (d) => d.id === nodeId)
            .classed('is-dim', (d) => !adj.has(d.id));
        nodes.select('.cit-core')
            .attr('filter', (d) => d.id === nodeId ? 'url(#cit-glow)' : null);
        edges
            .classed('is-active', (d) => {
                const sid = typeof d.source === 'object' ? d.source.id : d.source;
                const tid = typeof d.target === 'object' ? d.target.id : d.target;
                return sid === nodeId || tid === nodeId;
            })
            .attr('stroke-opacity', (d) => {
                const sid = typeof d.source === 'object' ? d.source.id : d.source;
                const tid = typeof d.target === 'object' ? d.target.id : d.target;
                return (sid === nodeId || tid === nodeId) ? 0.6 : 0.05;
            })
            .attr('stroke-width', (d) => {
                const sid = typeof d.source === 'object' ? d.source.id : d.source;
                const tid = typeof d.target === 'object' ? d.target.id : d.target;
                return (sid === nodeId || tid === nodeId) ? 1.4 : 0.6;
            });
    }

    // ---------- public API ----------

    function destroy() {
        if (!state) return;
        try { state.simulation?.stop(); } catch (e) { /* ignore */ }
        state.resizeObserver?.disconnect();
        state.tooltip?.remove();
        state.themeListener && document.removeEventListener('theme:change', state.themeListener);
        if (state.container) {
            state.container.classList.remove('cit-canvas--neural');
            state.container.innerHTML = '';
        }
        state = null;
    }

    function resolveContainer(selector) {
        if (selector instanceof Element) return selector;
        if (typeof selector === 'string') return document.querySelector(selector);
        return null;
    }

    function render(selector, data, callbacks) {
        const container = resolveContainer(selector);
        if (!container || typeof d3 === 'undefined') return null;

        destroy();
        // Preserve any overlay children (legend, zoom buttons) the markup added.
        // We only clear nodes that we ourselves create.
        Array.from(container.querySelectorAll('svg.cit-graph-svg, .cit-graph-tooltip'))
            .forEach((el) => el.remove());
        container.style.position = 'relative';
        container.style.overflow = 'hidden';
        // strip the previous "neural" override if it was left behind
        container.classList.remove('cit-canvas--neural');

        const palette = readPalette();

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 620;

        const svgRoot = d3.select(container)
            .insert('svg', ':first-child')
            .attr('class', 'cit-graph-svg')
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', `0 0 ${width} ${height}`)
            .style('display', 'block');

        const defs = svgRoot.append('defs');
        buildDefs(defs, palette);

        const root = svgRoot.append('g').attr('class', 'cit-root');
        const linkGroup = root.append('g').attr('class', 'cit-links');
        const nodeGroup = root.append('g').attr('class', 'cit-nodes');

        const zoom = d3.zoom()
            .scaleExtent([0.25, 4])
            .on('zoom', (event) => root.attr('transform', event.transform));
        svgRoot.call(zoom);

        // Click on empty background clears persistent highlight
        svgRoot.on('click', () => focusNode(null, true));

        const simulation = d3.forceSimulation()
            .force('link', d3.forceLink().id((d) => d.id).strength(0.5))
            .force('charge', d3.forceManyBody().strength(-280))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collide', d3.forceCollide((d) => radiusFor(d) + 5));

        const drag = d3.drag()
            .on('start', (event, d) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x; d.fy = d.y;
            })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => {
                if (!event.active) simulation.alphaTarget(0);
                // Auto-unpin so the layout stays alive after a drag.
                d.fx = null; d.fy = null;
            });

        const tooltip = ensureTooltip();

        const filters = {
            showRefs: true,
            showCiters: true,
            minCites: 0,
            yearRange: [-Infinity, Infinity],
        };

        const themeListener = () => applyTheme();
        document.addEventListener('theme:change', themeListener);

        state = {
            container,
            svg: svgRoot,
            root,
            defs,
            linkGroup,
            nodeGroup,
            simulation,
            drag,
            zoom,
            tooltip,
            palette,
            callbacks: callbacks || {},
            data: { nodes: [], edges: [] },
            filters,
            width,
            height,
            lockedHighlightId: null,
            yearExtent: [0, 0],
            yearScale: null,
            onLegendUpdate: callbacks?.onLegendUpdate || null,
            themeListener,
            dispatch(eventName, detail) {
                container.dispatchEvent(new CustomEvent(eventName, { detail, bubbles: true }));
                window.dispatchEvent(new CustomEvent(eventName, { detail }));
            },
        };

        if (typeof ResizeObserver !== 'undefined') {
            state.resizeObserver = new ResizeObserver(() => {
                if (!state) return;
                const w = container.clientWidth || state.width;
                const h = container.clientHeight || state.height;
                if (w === state.width && h === state.height) return;
                state.width = w; state.height = h;
                state.svg.attr('width', w).attr('height', h).attr('viewBox', `0 0 ${w} ${h}`);
                state.simulation.force('center', d3.forceCenter(w / 2, h / 2));
                state.simulation.alpha(0.3).restart();
            });
            state.resizeObserver.observe(container);
        }

        replaceData(data || { nodes: [], edges: [] });
        return state;
    }

    function replaceData(data) {
        if (!state) return;
        state.data = {
            nodes: Array.isArray(data?.nodes) ? data.nodes.map((n) => ({ ...n })) : [],
            edges: Array.isArray(data?.edges) ? data.edges.map((e) => ({ ...e })) : [],
        };
        state.lockedHighlightId = null;
        renderImpl();
    }

    function merge(addedNodes = [], addedEdges = []) {
        if (!state) return;
        const knownIds = new Set(state.data.nodes.map((n) => n.id));
        for (const node of addedNodes) {
            if (!knownIds.has(node.id)) {
                state.data.nodes.push({ ...node });
                knownIds.add(node.id);
            }
        }
        const edgeKey = (e) => {
            const sid = typeof e.source === 'object' ? e.source.id : e.source;
            const tid = typeof e.target === 'object' ? e.target.id : e.target;
            return `${sid}->${tid}:${e.kind}`;
        };
        const knownEdges = new Set(state.data.edges.map(edgeKey));
        for (const edge of addedEdges) {
            const key = edgeKey(edge);
            if (!knownEdges.has(key)) {
                state.data.edges.push({ ...edge });
                knownEdges.add(key);
            }
        }
        renderImpl();
    }

    function filter(filters) {
        if (!state) return;
        Object.assign(state.filters, filters || {});
        renderImpl();
    }

    function highlight(nodeId) {
        if (!state) return;
        focusNode(nodeId || null, true);
    }

    function zoomBy(factor) {
        if (!state) return;
        state.svg.transition().duration(240).call(state.zoom.scaleBy, factor);
    }

    function zoomReset() {
        if (!state) return;
        state.svg.transition().duration(420).call(state.zoom.transform, d3.zoomIdentity);
    }

    function applyTheme() {
        if (!state) return;
        state.palette = readPalette();
        buildDefs(state.defs, state.palette);
        renderImpl();
    }

    window.CitationGraph = {
        render(selector, data, callbacks) { return render(selector, data, callbacks); },
        replaceData,
        merge,
        filter,
        highlight,
        zoomBy,
        zoomReset,
        applyTheme,
        destroy,
        readPalette,           // exposed so Alpine can paint the year legend
        makeYearScale,
        computeYearExtent,
    };
})();
