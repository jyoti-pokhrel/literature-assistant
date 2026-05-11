/**
 * CitationGraph — d3-force directed graph for citation networks.
 *
 * Public surface:
 *   window.CitationGraph = {
 *     render(selector, data, callbacks),
 *     merge(addedNodes, addedEdges),
 *     filter({ showRefs, showCiters, minCites, yearRange }),
 *     highlight(nodeId),
 *     applyTheme(),
 *     destroy(),
 *   }
 *
 * Data shape:
 *   { nodes: [{ id, paper_id, title, year, authors, citation_count, role, doi, url }],
 *     edges: [{ source, target, kind: 'ref' | 'cite' }] }
 */
(function () {
    'use strict';

    let state = null;

    function readVar(name, fallback = '') {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    }

    function readPalette() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            isDark,
            seed: readVar('--c-1', isDark ? '#e8e4d8' : '#1a1816'),
            reference: readVar('--c-2', '#b86b3c'),
            citer: readVar('--c-3', '#c9a75e'),
            seedRing: readVar('--c-4', '#7a5a3a'),
            text: readVar('--ink', isDark ? '#e8e4d8' : '#1a1816'),
            textMuted: readVar('--ink-2', isDark ? '#8a8378' : '#6b665e'),
            edge: readVar('--rule-strong', isDark ? 'rgba(232,228,216,0.32)' : 'rgba(26,24,22,0.32)'),
            edgeFaint: readVar('--rule', isDark ? 'rgba(232,228,216,0.12)' : 'rgba(26,24,22,0.12)'),
            tooltipBg: readVar('--paper-2', isDark ? '#16140f' : '#efeadc'),
            tooltipBorder: readVar('--rule-strong', isDark ? 'rgba(232,228,216,0.18)' : 'rgba(26,24,22,0.18)'),
        };
    }

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

    function roleFill(role, palette) {
        if (role === 'seed') return palette.seed;
        if (role === 'citer') return palette.citer;
        return palette.reference;
    }

    function radiusFor(node) {
        const cc = Math.max(0, Number(node.citation_count) || 0);
        const r = 6 + 3.5 * Math.log(1 + cc);
        return Math.max(6, Math.min(38, r));
    }

    function destroy() {
        if (!state) return;
        try { state.simulation?.stop(); } catch (e) { /* ignore */ }
        state.resizeObserver?.disconnect();
        state.tooltip?.remove();
        state.themeListener && document.removeEventListener('theme:change', state.themeListener);
        if (state.container) {
            state.container.innerHTML = '';
        }
        state = null;
    }

    function _resolveContainer(selector) {
        if (selector instanceof Element) return selector;
        if (typeof selector === 'string') return document.querySelector(selector);
        return null;
    }

    function _ensureTooltip() {
        const palette = readPalette();
        const tip = d3.select(document.body)
            .append('div')
            .attr('class', 'cit-graph-tooltip')
            .style('position', 'absolute')
            .style('pointer-events', 'none')
            .style('opacity', 0)
            .style('z-index', 1100)
            .style('background', palette.tooltipBg)
            .style('backdrop-filter', 'blur(12px)')
            .style('-webkit-backdrop-filter', 'blur(12px)')
            .style('border', `1px solid ${palette.tooltipBorder}`)
            .style('border-radius', '10px')
            .style('padding', '10px 12px')
            .style('color', palette.text)
            .style('max-width', '320px')
            .style('font-size', '0.78rem')
            .style('line-height', '1.4')
            .style('box-shadow', '0 8px 24px rgba(0,0,0,0.18)')
            .style('transition', 'opacity 0.16s cubic-bezier(0.22,1,0.36,1)');
        return tip;
    }

    function tooltipHtml(node) {
        const title = escapeHtml(truncate(node.title, 90));
        const authors = Array.isArray(node.authors) ? node.authors.slice(0, 3) : [];
        const authorLabel = authors.length
            ? escapeHtml(authors.join(', ')) + (node.authors && node.authors.length > 3 ? ' et al.' : '')
            : '<span style="opacity:0.6">Authors unknown</span>';
        const roleLabel = node.role === 'seed' ? 'Seed' : node.role === 'citer' ? 'Citer' : 'Reference';
        const cc = Number.isFinite(node.citation_count) ? `${node.citation_count.toLocaleString()} citations` : '';
        const year = node.year || '—';
        return `
            <div style="font-weight:600; margin-bottom:4px;">${title}</div>
            <div style="font-size:0.72rem; opacity:0.85;">${authorLabel}</div>
            <div style="font-size:0.7rem; opacity:0.7; margin-top:6px; display:flex; gap:8px; flex-wrap:wrap;">
                <span>${year}</span>
                <span>·</span>
                <span>${roleLabel}</span>
                ${cc ? `<span>·</span><span>${cc}</span>` : ''}
            </div>
        `;
    }

    function _buildArrowMarkers(defs, palette) {
        defs.selectAll('marker.cit-arrow').remove();
        const makeMarker = (id, fill) => {
            defs.append('marker')
                .attr('class', 'cit-arrow')
                .attr('id', id)
                .attr('viewBox', '0 -5 10 10')
                .attr('refX', 14)
                .attr('refY', 0)
                .attr('markerWidth', 7)
                .attr('markerHeight', 7)
                .attr('orient', 'auto')
                .append('path')
                .attr('d', 'M0,-4 L8,0 L0,4 Z')
                .attr('fill', fill)
                .attr('opacity', 0.75);
        };
        makeMarker('cit-arrow-ref', palette.reference);
        makeMarker('cit-arrow-cite', palette.citer);
    }

    function _normaliseEdges(edges, nodeIndex) {
        // d3.forceLink needs node references (or matching ids) — keep as strings.
        return edges
            .filter((e) => nodeIndex.has(e.source) && nodeIndex.has(e.target))
            .map((e) => ({ ...e }));
    }

    function _applyFilterToSelection(data, filters) {
        const { showRefs, showCiters, minCites, yearRange } = filters;
        const [minYear, maxYear] = yearRange || [-Infinity, Infinity];
        const visibleNodeIds = new Set();
        for (const node of data.nodes) {
            if (node.role === 'seed') {
                visibleNodeIds.add(node.id);
                continue;
            }
            if (node.role === 'reference' && !showRefs) continue;
            if (node.role === 'citer' && !showCiters) continue;
            const cc = Number(node.citation_count) || 0;
            if (cc < (minCites || 0)) continue;
            const y = Number(node.year);
            if (Number.isFinite(y)) {
                if (y < minYear || y > maxYear) continue;
            }
            visibleNodeIds.add(node.id);
        }
        return visibleNodeIds;
    }

    function _renderImpl() {
        if (!state) return;
        const { container, data, palette, callbacks, filters } = state;

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 600;
        state.width = width;
        state.height = height;

        const svg = state.svg
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', `0 0 ${width} ${height}`);

        const visibleNodeIds = _applyFilterToSelection(data, filters);
        const renderNodes = data.nodes.filter((n) => visibleNodeIds.has(n.id));
        const renderEdges = data.edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));

        const nodeIndex = new Map(renderNodes.map((n) => [n.id, n]));

        // Pre-compute citation-count normalization for edge opacity.
        const cites = renderNodes.map((n) => Math.log(1 + (Number(n.citation_count) || 0)));
        const maxLog = cites.length ? Math.max(...cites) || 1 : 1;

        // Update simulation data.
        state.simulation.nodes(renderNodes);
        const link = state.linkGroup
            .selectAll('line')
            .data(_normaliseEdges(renderEdges, nodeIndex), (d) => `${d.source}->${d.target}:${d.kind}`);

        link.exit().remove();
        const linkEnter = link.enter()
            .append('line')
            .attr('stroke-width', 1.1)
            .attr('stroke-linecap', 'round')
            .attr('marker-end', (d) => d.kind === 'cite' ? 'url(#cit-arrow-cite)' : 'url(#cit-arrow-ref)');
        const linkMerged = linkEnter.merge(link)
            .attr('stroke', (d) => {
                const target = nodeIndex.get(d.target.id || d.target);
                const norm = target ? Math.log(1 + (Number(target.citation_count) || 0)) / maxLog : 0;
                const blend = 0.25 + 0.55 * norm;
                return d.kind === 'cite' ? palette.citer : palette.reference;
            })
            .attr('stroke-opacity', (d) => {
                const target = nodeIndex.get(d.target.id || d.target);
                const norm = target ? Math.log(1 + (Number(target.citation_count) || 0)) / maxLog : 0;
                return 0.22 + 0.45 * norm;
            });

        const linkSel = state.linkGroup.selectAll('line');

        const node = state.nodeGroup
            .selectAll('g.cit-node')
            .data(renderNodes, (d) => d.id);

        node.exit().remove();

        const nodeEnter = node.enter()
            .append('g')
            .attr('class', 'cit-node')
            .style('cursor', 'pointer')
            .call(state.drag);

        nodeEnter.append('circle')
            .attr('r', (d) => radiusFor(d))
            .attr('fill', (d) => roleFill(d.role, palette))
            .attr('stroke', (d) => d.role === 'seed' ? palette.seedRing : palette.tooltipBorder)
            .attr('stroke-width', (d) => d.role === 'seed' ? 2.5 : 1.2)
            .attr('opacity', 0.94);

        nodeEnter.append('title').text((d) => d.title || '');

        nodeEnter
            .on('mouseenter', function (event, d) {
                state.tooltip.html(tooltipHtml(d)).style('opacity', 1);
                d3.select(this).select('circle').attr('opacity', 1);
            })
            .on('mousemove', function (event) {
                state.tooltip
                    .style('left', `${event.pageX + 14}px`)
                    .style('top', `${event.pageY - 14}px`);
            })
            .on('mouseleave', function () {
                state.tooltip.style('opacity', 0);
                d3.select(this).select('circle').attr('opacity', 0.94);
            })
            .on('click', function (event, d) {
                if (event.shiftKey) {
                    d.fx = null;
                    d.fy = null;
                    state.simulation.alpha(0.3).restart();
                    return;
                }
                callbacks?.onSelect?.(d);
                state.dispatch('paper:select', { paper: d });
            })
            .on('dblclick', function (event, d) {
                event.preventDefault();
                callbacks?.onExpand?.(d.id, d);
            });

        const nodeMerged = nodeEnter.merge(node);
        nodeMerged.select('circle')
            .attr('r', (d) => radiusFor(d))
            .attr('fill', (d) => roleFill(d.role, palette))
            .attr('stroke', (d) => d.role === 'seed' ? palette.seedRing : palette.tooltipBorder)
            .attr('stroke-width', (d) => d.role === 'seed' ? 2.5 : 1.2);

        state.simulation
            .force('link').links(_normaliseEdges(renderEdges, nodeIndex).map((e) => ({ ...e })));

        state.simulation.alpha(0.85).restart();

        state.tickFn = function tick() {
            linkSel
                .attr('x1', (d) => (d.source.x ?? 0))
                .attr('y1', (d) => (d.source.y ?? 0))
                .attr('x2', (d) => (d.target.x ?? 0))
                .attr('y2', (d) => (d.target.y ?? 0));
            state.nodeGroup.selectAll('g.cit-node')
                .attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
        };
        state.simulation.on('tick', state.tickFn);
    }

    function render(selector, data, callbacks) {
        const container = _resolveContainer(selector);
        if (!container || typeof d3 === 'undefined') return null;

        destroy();
        container.innerHTML = '';
        container.style.position = 'relative';
        container.style.overflow = 'hidden';

        const palette = readPalette();

        const svgRoot = d3.select(container)
            .append('svg')
            .attr('width', container.clientWidth || 800)
            .attr('height', container.clientHeight || 600)
            .attr('class', 'cit-graph-svg')
            .style('display', 'block');

        const defs = svgRoot.append('defs');
        _buildArrowMarkers(defs, palette);

        const root = svgRoot.append('g').attr('class', 'cit-root');
        const linkGroup = root.append('g').attr('class', 'cit-links');
        const nodeGroup = root.append('g').attr('class', 'cit-nodes');

        const zoom = d3.zoom()
            .scaleExtent([0.2, 4])
            .on('zoom', (event) => {
                root.attr('transform', event.transform);
            });
        svgRoot.call(zoom);

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 600;

        const simulation = d3.forceSimulation()
            .force('link', d3.forceLink()
                .id((d) => d.id)
                .distance((d) => {
                    const target = (typeof d.target === 'object' ? d.target : null);
                    const cc = target ? (Number(target.citation_count) || 0) : 0;
                    return 60 + 4 * Math.log(1 + cc);
                })
                .strength(0.6))
            .force('charge', d3.forceManyBody().strength(-260))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collide', d3.forceCollide((d) => radiusFor(d) + 4));

        const drag = d3.drag()
            .on('start', (event, d) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            })
            .on('drag', (event, d) => {
                d.fx = event.x;
                d.fy = event.y;
            })
            .on('end', (event, d) => {
                if (!event.active) simulation.alphaTarget(0);
                // Keep pinned by default; shift+click clears the pin.
            });

        const tooltip = _ensureTooltip();

        const filters = {
            showRefs: true,
            showCiters: true,
            minCites: 0,
            yearRange: [-Infinity, Infinity],
        };

        // Listen for theme changes.
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
            callbacks: callbacks || {},
            data: { nodes: [], edges: [] },
            filters,
            width,
            height,
            palette,
            themeListener,
            dispatch(eventName, detail) {
                container.dispatchEvent(new CustomEvent(eventName, { detail, bubbles: true }));
                window.dispatchEvent(new CustomEvent(eventName, { detail }));
            },
        };

        // Resize handling.
        if (typeof ResizeObserver !== 'undefined') {
            state.resizeObserver = new ResizeObserver(() => {
                if (!state) return;
                const w = container.clientWidth || state.width;
                const h = container.clientHeight || state.height;
                if (w === state.width && h === state.height) return;
                state.width = w;
                state.height = h;
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
        _renderImpl();
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
        const edgeKey = (e) => `${e.source}->${e.target}:${e.kind}`;
        const knownEdges = new Set(state.data.edges.map(edgeKey));
        for (const edge of addedEdges) {
            const key = edgeKey(edge);
            if (!knownEdges.has(key)) {
                state.data.edges.push({ ...edge });
                knownEdges.add(key);
            }
        }
        _renderImpl();
    }

    function filter(filters) {
        if (!state) return;
        Object.assign(state.filters, filters || {});
        _renderImpl();
    }

    function highlight(nodeId) {
        if (!state) return;
        state.nodeGroup.selectAll('g.cit-node').select('circle')
            .attr('opacity', (d) => (!nodeId || d.id === nodeId ? 1 : 0.22));
        state.linkGroup.selectAll('line')
            .attr('stroke-opacity', (d) => {
                if (!nodeId) return 0.5;
                const srcId = d.source.id || d.source;
                const tgtId = d.target.id || d.target;
                return srcId === nodeId || tgtId === nodeId ? 0.85 : 0.08;
            });
    }

    function applyTheme() {
        if (!state) return;
        state.palette = readPalette();
        _buildArrowMarkers(state.defs, state.palette);
        _renderImpl();
        if (state.tooltip) {
            state.tooltip
                .style('background', state.palette.tooltipBg)
                .style('border-color', state.palette.tooltipBorder)
                .style('color', state.palette.text);
        }
    }

    window.CitationGraph = {
        render(selector, data, callbacks) {
            return render(selector, data, callbacks);
        },
        replaceData,
        merge,
        filter,
        highlight,
        applyTheme,
        destroy,
    };
})();
