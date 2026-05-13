document.addEventListener('alpine:init', () => {
    Alpine.data('citationGraph', () => ({
        input: '',
        resolving: false,
        resolved: null,         // { paper_id, source, doi, title, year, url }
        building: false,
        progress: { stage: '', message: '', nodes: 0, edges: 0 },
        warnings: [],
        errorMsg: '',
        cached: false,
        sourcesUsed: [],
        graph: { nodes: [], edges: [] },
        selectedNode: null,
        filters: {
            showRefs: true,
            showCiters: true,
            minCites: 0,
            yearMin: 1900,
            yearMax: 2026,
        },
        meta: { totalNodes: 0, totalEdges: 0, refs: 0, citers: 0, yearMin: 1900, yearMax: 2026 },
        topCited: [],

        init() {
            this._abortController = null;
            this._themeListener = () => window.CitationGraph?.applyTheme?.();
            document.addEventListener('theme:change', this._themeListener);

            this.$watch('$store.app.currentView', (next, prev) => {
                if (prev === 'citations' && next !== 'citations') {
                    this._teardownGraph();
                }
            });

            this.$watch('filters', () => this._applyFiltersToGraph(), { deep: true });

            // Keep the year sliders ordered — dragging one past the other would
            // produce an empty year range and silently blank the graph.
            this.$watch('filters.yearMin', (v) => {
                const n = Number(v);
                if (Number.isFinite(n) && n > Number(this.filters.yearMax)) {
                    this.filters.yearMax = n;
                }
            });
            this.$watch('filters.yearMax', (v) => {
                const n = Number(v);
                if (Number.isFinite(n) && n < Number(this.filters.yearMin)) {
                    this.filters.yearMin = n;
                }
            });
        },

        destroy() {
            this._teardownGraph();
            document.removeEventListener('theme:change', this._themeListener);
            if (this._abortController) {
                try { this._abortController.abort(); } catch (e) { /* ignore */ }
                this._abortController = null;
            }
        },

        _teardownGraph() {
            try { window.CitationGraph?.destroy?.(); } catch (e) { /* ignore */ }
        },

        _resetForBuild() {
            this.warnings = [];
            this.errorMsg = '';
            this.progress = { stage: '', message: '', nodes: 0, edges: 0 };
            this.graph = { nodes: [], edges: [] };
            this.selectedNode = null;
            this.topCited = [];
            this.cached = false;
            this.sourcesUsed = [];
        },

        async resolve() {
            const value = (this.input || '').trim();
            if (!value) {
                this.errorMsg = 'Paste a DOI, arXiv ID, or paper URL first.';
                return;
            }
            this.errorMsg = '';
            this.resolving = true;
            this.resolved = null;
            try {
                const res = await fetch('/citations/resolve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ input: value }),
                });
                if (!res.ok) {
                    const body = await res.json().catch(() => ({}));
                    this.errorMsg = body.detail || 'We could not recognize that identifier.';
                    return;
                }
                this.resolved = await res.json();
            } catch (err) {
                this.errorMsg = err?.message || 'Resolve failed';
            } finally {
                this.resolving = false;
            }
        },

        async build() {
            if (!this.resolved) {
                await this.resolve();
                if (!this.resolved) return;
            }
            this._resetForBuild();
            this.building = true;

            const controller = new AbortController();
            this._abortController = controller;

            try {
                const res = await fetch('/citations/network', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ paper_id: this.resolved.paper_id }),
                    signal: controller.signal,
                });
                if (!res.ok || !res.body) {
                    this.errorMsg = `Build failed: HTTP ${res.status}`;
                    return;
                }
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buf = '';
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    buf += decoder.decode(value, { stream: true });
                    let nl;
                    while ((nl = buf.indexOf('\n')) !== -1) {
                        const line = buf.slice(0, nl).trim();
                        buf = buf.slice(nl + 1);
                        if (!line) continue;
                        try {
                            this._handleEvent(JSON.parse(line));
                        } catch (parseErr) {
                            console.warn('Bad NDJSON line', line, parseErr);
                        }
                    }
                }
            } catch (err) {
                if (err?.name !== 'AbortError') {
                    this.errorMsg = err?.message || 'Build failed';
                }
            } finally {
                this.building = false;
                this._abortController = null;
            }
        },

        cancel() {
            if (this._abortController) {
                try { this._abortController.abort(); } catch (e) { /* ignore */ }
                this._abortController = null;
            }
            this.building = false;
        },

        _handleEvent(evt) {
            switch (evt?.type) {
                case 'progress':
                    this.progress.stage = evt.stage || this.progress.stage;
                    this.progress.message = evt.message || this.progress.message;
                    return;
                case 'count':
                    this.progress.nodes = Number(evt.nodes) || this.progress.nodes;
                    this.progress.edges = Number(evt.edges) || this.progress.edges;
                    return;
                case 'warning':
                    this.warnings.push({ code: evt.code || '', message: evt.message || '' });
                    return;
                case 'error':
                    this.errorMsg = evt.detail || 'Unknown error';
                    return;
                case 'result':
                    this._loadResult(evt.data || {});
                    return;
                case 'done':
                    return;
                default:
                    return;
            }
        },

        _loadResult(data) {
            const nodes = Array.isArray(data.nodes) ? data.nodes : [];
            const edges = Array.isArray(data.edges) ? data.edges : [];
            this.graph = { nodes, edges };
            this.cached = !!data.cached;
            this.sourcesUsed = Array.isArray(data.sources_used) ? data.sources_used : [];
            this._recomputeMeta();
            this._mountGraph();
            this._recomputeTopCited();
        },

        _recomputeMeta() {
            const nodes = this.graph.nodes;
            let refs = 0, citers = 0, yMin = Infinity, yMax = -Infinity, yearsSeen = 0;
            for (const n of nodes) {
                if (n.role === 'reference') refs += 1;
                else if (n.role === 'citer') citers += 1;
                if (n.year == null || n.year === '') continue;
                const y = Number(n.year);
                if (!Number.isFinite(y) || y < 1500 || y > 2100) continue;
                yearsSeen += 1;
                if (y < yMin) yMin = y;
                if (y > yMax) yMax = y;
            }
            const safeMin = yearsSeen ? yMin : 1900;
            const safeMax = yearsSeen ? yMax : new Date().getFullYear();
            this.meta = {
                totalNodes: nodes.length,
                totalEdges: this.graph.edges.length,
                refs,
                citers,
                yearMin: safeMin,
                yearMax: safeMax,
                yearsKnown: yearsSeen > 0,
            };
            this.filters.yearMin = safeMin;
            this.filters.yearMax = safeMax;
        },

        _recomputeTopCited() {
            const sorted = [...this.graph.nodes]
                .filter((n) => n.role !== 'seed')
                .sort((a, b) => (Number(b.citation_count) || 0) - (Number(a.citation_count) || 0))
                .slice(0, 10);
            this.topCited = sorted;
        },

        _mountGraph() {
            this.$nextTick(() => {
                const mount = this.$refs?.graphMount || document.getElementById('cit-graph-mount');
                if (!mount) return;
                window.CitationGraph?.render(mount, this.graph, {
                    onSelect: (node) => { this.selectNode(node); },
                    onExpand: (nodeId) => { this.expand(nodeId); },
                });
                this._applyFiltersToGraph();
            });
        },

        _applyFiltersToGraph() {
            window.CitationGraph?.filter?.({
                showRefs: !!this.filters.showRefs,
                showCiters: !!this.filters.showCiters,
                minCites: Number(this.filters.minCites) || 0,
                yearRange: [
                    Number(this.filters.yearMin) || -Infinity,
                    Number(this.filters.yearMax) || Infinity,
                ],
            });
        },

        selectNode(node) {
            this.selectedNode = node || null;
            if (node?.id) {
                window.CitationGraph?.highlight?.(node.id);
            } else {
                window.CitationGraph?.highlight?.(null);
            }
        },

        clearSelection() {
            this.selectedNode = null;
            window.CitationGraph?.highlight?.(null);
        },

        async expand(nodeId, direction = 'both') {
            if (!this.resolved?.paper_id || !nodeId) return;
            try {
                const knownIds = this.graph.nodes.map((n) => n.id);
                const res = await fetch(
                    `/citations/network/${encodeURIComponent(this.resolved.paper_id)}/expand`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ node_id: nodeId, direction, known_ids: knownIds }),
                    }
                );
                if (!res.ok) {
                    const body = await res.json().catch(() => ({}));
                    this.errorMsg = body.detail || `Expansion failed (HTTP ${res.status})`;
                    return;
                }
                const data = await res.json();
                const addedNodes = data.added_nodes || [];
                const addedEdges = data.added_edges || [];
                if (!addedNodes.length && !addedEdges.length) return;

                // Merge into local graph state.
                const existing = new Set(this.graph.nodes.map((n) => n.id));
                for (const n of addedNodes) {
                    if (!existing.has(n.id)) {
                        this.graph.nodes.push(n);
                        existing.add(n.id);
                    }
                }
                const edgeKey = (e) => `${e.source}->${e.target}:${e.kind}`;
                const existingEdges = new Set(this.graph.edges.map(edgeKey));
                for (const e of addedEdges) {
                    const key = edgeKey(e);
                    if (!existingEdges.has(key)) {
                        this.graph.edges.push(e);
                        existingEdges.add(key);
                    }
                }
                window.CitationGraph?.merge?.(addedNodes, addedEdges);
                this._recomputeMeta();
                this._recomputeTopCited();
            } catch (err) {
                this.errorMsg = err?.message || 'Expansion failed';
            }
        },

        paperLink(node) {
            if (!node) return '';
            if (node.url) return node.url;
            if (node.doi) return `https://doi.org/${node.doi}`;
            if (typeof node.paper_id === 'string' && node.paper_id.startsWith('ARX:')) {
                return `https://arxiv.org/abs/${node.paper_id.slice(4)}`;
            }
            if (typeof node.paper_id === 'string' && node.paper_id.length === 40) {
                return `https://www.semanticscholar.org/paper/${node.paper_id}`;
            }
            return '';
        },

        roleLabel(role) {
            if (role === 'seed') return 'Seed';
            if (role === 'citer') return 'Citer';
            return 'Reference';
        },

        stageLabel(stage) {
            const map = {
                cache_lookup: 'Checking cache',
                cache_hit: 'Served from cache',
                resolve_seed: 'Resolving seed paper',
                fetch_refs: 'Fetching references',
                fetch_citers: 'Fetching citers',
                merge: 'Merging sources',
                cache_write: 'Caching network',
            };
            return map[stage] || stage || '';
        },
    }));
});
