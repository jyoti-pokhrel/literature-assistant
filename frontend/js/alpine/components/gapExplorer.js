document.addEventListener('alpine:init', () => {
    Alpine.data('gapExplorer', () => ({
        init() {
            this.ensureStore();
            this.$nextTick(() => {
                this.renderClusterMap();
                this.renderCharts();
                this.autoSelectFirstGap();
            });
            this.$watch('$store.app.result', () => {
                this.resetSelection();
                this.$nextTick(() => {
                    this.renderClusterMap();
                    this.renderCharts();
                    this.autoSelectFirstGap();
                });
            });
            this.$watch('$store.app.isLoading', (loading) => {
                if (!loading) {
                    this.$nextTick(() => {
                        this.renderClusterMap();
                        this.renderCharts();
                        this.autoSelectFirstGap();
                    });
                }
            });
            this.$watch('$store.app.theme', () => this.$nextTick(() => this.renderCharts()));
            this.$watch('$store.app.explorer.selectedGapId', () => this.$nextTick(() => this.renderCharts()));
            this.$watch('$store.app.explorer.filters.minConfidence', () => this.syncMapFilterHighlight());
            this.$watch('$store.app.explorer.filters.maxConfidence', () => this.syncMapFilterHighlight());
            this.$watch('$store.app.explorer.filters.clusterId', () => this.syncMapFilterHighlight());
            this.$watch('$store.app.explorer.filters.searchText', () => this.syncMapFilterHighlight());
        },

        autoSelectFirstGap() {
            if (this.$store.app.explorer.panelOpen) return;
            const first = this.gaps()[0];
            if (first) this.selectGap(first);
        },

        ensureStore() {
            if (!this.$store.app.explorer) {
                this.$store.app.explorer = this.defaultExplorerState();
            }
            if (!this.$store.app.explorer.filters) {
                this.$store.app.explorer.filters = this.defaultExplorerState().filters;
            }
        },

        defaultExplorerState() {
            return {
                selectedGapId: null,
                selectedPaperId: null,
                selectedClusterId: null,
                panelOpen: false,
                panelType: null,
                filters: {
                    minConfidence: 0,
                    maxConfidence: 1,
                    clusterId: '',
                    searchText: '',
                    sortBy: 'confidence_desc',
                },
            };
        },

        resetSelection() {
            Object.assign(this.$store.app.explorer, {
                selectedGapId: null,
                selectedPaperId: null,
                selectedClusterId: null,
                panelOpen: false,
                panelType: null,
            });
            window.ClusterMap?.clearHighlight();
        },

        filters() {
            return this.$store.app.explorer.filters;
        },

        gaps() {
            if (this.$store.app.isLoading) return [];
            return this.$store.app.result?.gapData?.gaps || [];
        },

        validGaps() {
            return this.gaps();
        },

        clusters() {
            if (this.$store.app.isLoading) return [];
            return this.$store.app.result?.gapData?.clusters || this.$store.app.result?.searchData?.clusters || [];
        },

        visualizations() {
            if (this.$store.app.isLoading) return null;
            return this.$store.app.result?.gapData?.visualizations || this.$store.app.result?.searchData?.visualizations || null;
        },

        patternAnalysis() {
            if (this.$store.app.isLoading) return null;
            return this.$store.app.result?.gapData?.pattern_analysis || this.$store.app.result?.searchData?.pattern_analysis || null;
        },

        hasChartData() {
            if (this.$store.app.isLoading) return false;
            const hasGaps = this.gaps().length > 0;
            const hasPapers = this.papers().length > 0;
            const pa = this.patternAnalysis();
            const hasPattern = pa && (
                Object.keys(pa.method_trend_by_year || {}).length > 0 ||
                Object.keys(pa.dataset_frequency || {}).length > 0 ||
                Object.keys(pa.metric_frequency || {}).length > 0
            );
            return hasGaps || this.hasYearChartData() || this.clusters().length > 0 || hasPattern;
        },

        hasYearChartData() {
            return this.papers().some((paper) => {
                const year = parseInt(paper?.year, 10);
                return year && year > 1900 && year < 2100;
            });
        },

        renderCharts() {
            if (!window.FrontendCharts) return;
            window.FrontendCharts.renderAll(
                {
                    confidenceBars: this.$refs.chartConfidence,
                    yearDist: this.$refs.chartYear,
                    clusterSizes: this.$refs.chartClusters,
                    methodTrends: this.$refs.chartMethods,
                    datasetFreq: this.$refs.chartDatasets,
                    metricFreq: this.$refs.chartMetrics,
                },
                {
                    gaps: this.validGaps(),
                    papers: this.papers(),
                    clusters: this.clusters(),
                    patternAnalysis: this.patternAnalysis(),
                    selectedGap: this.selectedGap(),
                }
            );
        },

        papers() {
            if (this.$store.app.isLoading) return [];
            const topLevel = this.$store.app.result?.searchData?.papers || [];
            const clusters = this.clusters();
            const clusterPapers = clusters.flatMap((cluster) => (cluster.papers || []).map((paper) => ({
                ...paper,
                cluster_id: cluster.cluster_id,
            })));
            const byKey = new Map();

            topLevel.forEach((paper, index) => {
                const key = this.paperKey(paper, index);
                const clusterMatch = this.findClusterPaper(paper);
                byKey.set(key, {
                    ...clusterMatch,
                    ...paper,
                    cluster_id: clusterMatch?.cluster_id ?? paper.cluster_id ?? null,
                });
            });

            clusterPapers.forEach((paper, index) => {
                const key = this.paperKey(paper, `cluster-${index}`);
                const titleKey = this.titleKey(paper.title);
                const existingKey = [...byKey.keys()].find((candidate) => candidate === key || this.titleKey(byKey.get(candidate)?.title) === titleKey);
                if (existingKey) {
                    byKey.set(existingKey, { ...paper, ...byKey.get(existingKey), cluster_id: paper.cluster_id });
                } else {
                    byKey.set(key, paper);
                }
            });

            return [...byKey.values()];
        },

        titleKey(title) {
            return String(title || '').trim().toLowerCase();
        },

        paperKey(paper, fallback = '') {
            return String(paper?.paper_id || paper?.external_id || paper?.url || this.titleKey(paper?.title) || fallback);
        },

        gapKey(gap, fallback = '') {
            return String(gap?.gap_id || this.titleKey(gap?.gap_title) || fallback);
        },

        findClusterPaper(paper) {
            const key = this.paperKey(paper);
            const title = this.titleKey(paper?.title);
            for (const cluster of this.clusters()) {
                const found = (cluster.papers || []).find((candidate) => {
                    return this.paperKey(candidate) === key || (title && this.titleKey(candidate.title) === title);
                });
                if (found) {
                    return { ...found, cluster_id: cluster.cluster_id };
                }
            }
            return null;
        },

        findPaperByReference(reference) {
            const key = this.paperKey(reference);
            const title = this.titleKey(reference?.title);
            return this.papers().find((paper) => {
                return this.paperKey(paper) === key || (title && this.titleKey(paper.title) === title);
            }) || reference;
        },

        findGap(gapId) {
            return this.gaps().find((gap, index) => this.gapKey(gap, index) === String(gapId)) || null;
        },

        findPaper(paperId) {
            return this.papers().find((paper, index) => this.paperKey(paper, index) === String(paperId)) || null;
        },

        findCluster(clusterId) {
            return this.clusters().find((cluster) => String(cluster.cluster_id) === String(clusterId)) || null;
        },

        clusterTrend(cluster) {
            return cluster?.trend_status || 'Established';
        },

        clusterTrendIcon(cluster) {
            const trend = this.clusterTrend(cluster);
            if (trend === 'Emerging') return 'M2 8 L8 2 M4 2 L8 2 L8 6';
            if (trend === 'Saturated') return 'M2 2 L8 8 M4 8 L8 8 L8 4';
            return 'M2 5 L8 5';
        },

        clusterColor(clusterId) {
            const colors = window.ClusterMap?.colors || ['#4e79a7'];
            const index = Math.abs(Number(clusterId) || 0) % colors.length;
            return colors[index];
        },

        confidence(gap) {
            const value = Number(gap?.confidence_score ?? 0);
            return Number.isFinite(value) ? value : 0;
        },

        clusterOptions() {
            return this.clusters().map((cluster) => ({
                id: String(cluster.cluster_id),
                label: `Cluster ${cluster.cluster_id}`,
                trend: this.clusterTrend(cluster),
                count: cluster.paper_count || cluster.papers?.length || 0,
            }));
        },

        filteredGaps() {
            const filters = this.filters();
            const search = this.titleKey(filters.searchText);
            const min = Number(filters.minConfidence ?? 0);
            const max = Number(filters.maxConfidence ?? 1);
            const clusterId = filters.clusterId === null || filters.clusterId === undefined ? '' : String(filters.clusterId);

            const filtered = this.gaps().filter((gap) => {
                const score = this.confidence(gap);
                const text = [
                    gap.gap_title,
                    gap.description,
                    gap.what_fails,
                    gap.missing_piece,
                    gap.why_it_exists,
                    gap.proposed_direction,
                    gap.pattern_detected,
                ].join(' ').toLowerCase();

                return score >= min
                    && score <= max
                    && (!clusterId || String(gap.cluster_id) === clusterId)
                    && (!search || text.includes(search));
            });

            const sorted = filtered.sort((a, b) => {
                if (filters.sortBy === 'confidence_asc') return this.confidence(a) - this.confidence(b);
                if (filters.sortBy === 'cluster') return Number(a.cluster_id ?? 0) - Number(b.cluster_id ?? 0);
                return this.confidence(b) - this.confidence(a);
            });

            return sorted;
        },

        hasActiveFilters() {
            const filters = this.filters();
            return Number(filters.minConfidence) > 0
                || Number(filters.maxConfidence) < 1
                || Boolean(filters.clusterId)
                || Boolean(String(filters.searchText || '').trim());
        },

        activeFilterPills() {
            const filters = this.filters();
            const pills = [];
            if (Number(filters.minConfidence) > 0) pills.push(`Min ${Number(filters.minConfidence).toFixed(2)}`);
            if (Number(filters.maxConfidence) < 1) pills.push(`Max ${Number(filters.maxConfidence).toFixed(2)}`);
            if (filters.clusterId) pills.push(`Cluster ${filters.clusterId}`);
            if (String(filters.searchText || '').trim()) pills.push(`Search "${filters.searchText.trim()}"`);
            return pills;
        },

        clearFilters() {
            Object.assign(this.$store.app.explorer.filters, {
                minConfidence: 0,
                maxConfidence: 1,
                clusterId: '',
                searchText: '',
                sortBy: 'confidence_desc',
            });
            this.syncMapFilterHighlight();
        },

        renderClusterMap() {
            const container = this.$refs.clusterMap;
            if (!container || this.$store.app.isLoading) return;
            window.ClusterMap?.render(container, this.clusters());
            this.syncMapFilterHighlight();
        },

        syncMapFilterHighlight() {
            if (!window.ClusterMap) return;
            const selectedGap = this.selectedGap();
            const selectedPaper = this.selectedPaper();
            if (selectedGap) {
                window.ClusterMap.highlightPapers(this.supportingPaperIds(selectedGap));
                return;
            }
            if (selectedPaper) {
                window.ClusterMap.highlightPapers([this.paperKey(selectedPaper)]);
                return;
            }
            if (!this.hasActiveFilters()) {
                window.ClusterMap.clearHighlight();
                return;
            }
            window.ClusterMap.highlightPapers(this.filteredPaperIds());
        },

        filteredPaperIds() {
            const ids = new Set();
            this.filteredGaps().forEach((gap) => {
                this.supportingPaperIds(gap).forEach((id) => ids.add(id));
            });
            const clusterId = this.filters().clusterId;
            if (clusterId) {
                (this.findCluster(clusterId)?.papers || []).forEach((paper, index) => ids.add(this.paperKey(paper, index)));
            }
            return [...ids];
        },

        supportingPapers(gap) {
            return gap?.citations || [];
        },

        supportingPaperIds(gap) {
            const ids = new Set();
            (gap?.supporting_papers || []).forEach((id) => ids.add(String(id)));
            this.supportingPapers(gap).forEach((paper, index) => {
                const matched = this.findPaperByReference(paper);
                ids.add(this.paperKey(matched, index));
                if (paper.title) ids.add(this.titleKey(paper.title));
                if (paper.paper_id) ids.add(String(paper.paper_id));
            });
            return [...ids].filter(Boolean);
        },

        paperGaps(paper) {
            const key = this.paperKey(paper);
            const title = this.titleKey(paper?.title);
            return this.gaps().filter((gap) => {
                return this.supportingPaperIds(gap).some((id) => id === key || id === title)
                    || this.supportingPapers(gap).some((candidate) => this.titleKey(candidate.title) === title);
            });
        },

        selectedGap() {
            return this.findGap(this.$store.app.explorer.selectedGapId);
        },

        selectedPaper() {
            return this.findPaper(this.$store.app.explorer.selectedPaperId);
        },

        selectedCluster() {
            return this.findCluster(this.$store.app.explorer.selectedClusterId);
        },

        panelTitle() {
            if (this.$store.app.explorer.panelType === 'gap') return this.selectedGap()?.gap_title || 'Research gap';
            if (this.$store.app.explorer.panelType === 'paper') return this.selectedPaper()?.title || 'Paper';
            if (this.$store.app.explorer.panelType === 'cluster') return `Cluster ${this.selectedCluster()?.cluster_id ?? ''}`;
            return '';
        },

        selectGap(gap) {
            const id = this.gapKey(gap);
            Object.assign(this.$store.app.explorer, {
                selectedGapId: id,
                selectedPaperId: null,
                selectedClusterId: gap?.cluster_id ?? null,
                panelType: 'gap',
                panelOpen: true,
            });
            window.ClusterMap?.highlightPapers(this.supportingPaperIds(gap));
            this.scrollToCard('gap', id);
        },

        selectPaper(paper) {
            const matched = this.findPaperByReference(paper);
            const id = this.paperKey(matched);
            Object.assign(this.$store.app.explorer, {
                selectedGapId: null,
                selectedPaperId: id,
                selectedClusterId: matched?.cluster_id ?? paper?.cluster_id ?? null,
                panelType: 'paper',
                panelOpen: true,
            });
            window.ClusterMap?.highlightPapers([id, this.titleKey(matched?.title)]);
            this.scrollToCard('paper', id);
        },

        selectCluster(cluster) {
            const clusterId = cluster?.cluster_id ?? null;
            // Find a representative gap for the clicked cluster so the
            // sidebar spider has something to render: prefer the cluster's
            // linked gap_id, fall back to the highest-confidence gap whose
            // cluster_id matches.
            let representativeGap = null;
            if (cluster?.gap_id) {
                representativeGap = this.gaps().find((g) => g.gap_id === cluster.gap_id) || null;
            }
            if (!representativeGap && clusterId !== null) {
                const matched = this.gaps()
                    .filter((g) => String(g.cluster_id) === String(clusterId))
                    .sort((a, b) => Number(b.confidence_score ?? 0) - Number(a.confidence_score ?? 0));
                representativeGap = matched[0] || null;
            }

            Object.assign(this.$store.app.explorer, {
                selectedGapId: representativeGap ? this.gapKey(representativeGap) : null,
                selectedPaperId: null,
                selectedClusterId: clusterId,
                panelType: representativeGap ? 'gap' : 'cluster',
                panelOpen: true,
            });
            this.$store.app.explorer.filters.clusterId = clusterId === null ? '' : String(clusterId);
            window.ClusterMap?.highlightPapers((cluster?.papers || []).map((paper, index) => this.paperKey(paper, index)));
        },

        closePanel() {
            this.resetSelection();
            this.syncMapFilterHighlight();
        },

        handlePaperSelect(event) {
            this.selectPaper(event.detail?.paper);
        },

        handleClusterSelect(event) {
            this.selectCluster(event.detail?.cluster);
        },

        handleMapClear() {
            this.closePanel();
        },

        scrollToCard(type, id) {
            this.$nextTick(() => {
                const escaped = window.CSS?.escape ? CSS.escape(String(id)) : String(id).replace(/"/g, '\\"');
                const element = this.$root.querySelector(`[data-${type}-id="${escaped}"]`);
                element?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            });
        },

        hasValue(val) {
            if (val === undefined || val === null) return false;
            const cleanStr = String(val).replace(/undefined/gi, '').trim();
            return cleanStr.length > 0 && cleanStr !== 'null';
        },

        getCitationLink(citation) {
            if (citation?.url) return citation.url;
            const match = this.papers().find((paper) => paper.title && citation?.title && paper.title.toLowerCase() === citation.title.toLowerCase());
            return match ? this.paperLink(match) : null;
        },

        paperLink(paper) {
            return paper?.url || paper?.pdf_url || '';
        },

        sourceLabel(source) {
            if (!source) return 'Unknown source';
            return window.searchAPI.sourceLabel(source);
        },

        supportingPaperMeta(paper) {
            const parts = [];
            if (paper?.venue && paper.venue !== 'Unknown Venue') parts.push(paper.venue);
            if (paper?.year) parts.push(String(paper.year));
            if (paper?.citation_count) parts.push(`${paper.citation_count} cites`);
            return parts.join(' · ');
        },

        supportCountLabel(gap) {
            const count = gap?.citations?.length || gap?.supporting_papers?.length || 0;
            return `${count} supporting paper${count === 1 ? '' : 's'}`;
        },

        validationLabel(gap) {
            if (gap?.cross_paper_validation?.status?.toLowerCase() === 'potentially_addressed') {
                return 'Potentially Addressed';
            }
            const validation = gap?.citation_validation || {};
            if (validation.status === 'grounded') {
                return `Citation grounded · ${validation.evidence_snippet_count || 0} snippets`;
            }
            if (validation.status === 'weakly_supported') {
                return 'Weakly Supported';
            }
            return `Needs review · ${(validation.issues || []).length || 0} checks`;
        },

        scoreBreakdown(gap) {
            const breakdown = gap?.score_breakdown || {};
            return [
                ['support', 'Support'],
                ['severity', 'Severity'],
                ['actionability', 'Actionability'],
                ['novelty', 'Novelty'],
                ['citation_confidence', 'Citation'],
            ]
                .filter(([key]) => breakdown[key] !== undefined)
                .map(([key, label]) => ({
                    key,
                    label,
                    value: Number(breakdown[key] || 0).toFixed(2)
                }));
        },

        renderTextWithCitations(text, gap) {
            if (!this.hasValue(text)) return '';
            const citations = this.supportingPapers(gap);

            // Step 1: split grouped citations like [1, 2] into individual [1][2]
            let processed = String(text).replace(/\[(\d+(?:\s*,\s*\d+)+)\]/g, (_, inner) => {
                return inner.split(',').map(n => `[${n.trim()}]`).join('');
            });

            // Step 2: render each [N] as a badge (linked if URL exists, hide if not)
            return processed.replace(/\[(\d+)\]/g, (match, n) => {
                const idx = parseInt(n, 10) - 1;
                const citation = citations[idx];
                const link = this.getCitationLink(citation);

                if (link) {
                    return `<a href="${link}" target="_blank" rel="noopener noreferrer" class="cite-badge">${match}</a>`;
                }

                // No URL: strip the citation marker entirely so it doesn't show in the UI
                return '';
            });
        },
    }));
});
