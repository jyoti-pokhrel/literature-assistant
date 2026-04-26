document.addEventListener('alpine:init', () => {
    Alpine.data('resultsPage', () => ({
        title() {
            return this.$store.app.form.topic || this.$store.app.result?.searchData?.topic || 'Search results';
        },

        meta() {
            const searchData = this.$store.app.result?.searchData;
            const filters = this.activeFilters();
            const paperCount = searchData?.count ?? searchData?.papers?.length ?? 0;

            if (this.$store.app.isLoading) {
                return filters.length ? filters.join(' · ') : 'Topic only';
            }

            return filters.length
                ? `${paperCount} paper${paperCount === 1 ? '' : 's'} · ${filters.join(' · ')}`
                : `${paperCount} paper${paperCount === 1 ? '' : 's'} · query only`;
        },

        papers() {
            if (this.$store.app.isLoading) {
                return [];
            }
            return this.$store.app.result?.searchData?.papers || [];
        },

        gaps() {
            if (this.$store.app.isLoading) {
                return [];
            }
            return this.$store.app.result?.gapData?.gaps || [];
        },

        activeFilters() {
            const searchDataFilters = this.$store.app.isLoading ? null : this.$store.app.result?.searchData?.filters;
            if (searchDataFilters) {
                return window.searchAPI.formatFilters(searchDataFilters);
            }

            const filters = {};
            const year = typeof this.$store.app.form.year === 'string' ? this.$store.app.form.year.trim() : '';
            const venue = typeof this.$store.app.form.venue === 'string' ? this.$store.app.form.venue.trim() : '';

            if (year) {
                filters.year = year.replace(/\s*-\s*/g, '-');
            }
            if (venue) {
                filters.venue = venue;
            }

            return window.searchAPI.formatFilters(filters);
        },

        sourceBadges() {
            if (this.$store.app.isLoading) {
                return [];
            }
            return (this.$store.app.result?.searchData?.sources_used || []).map((source) => window.searchAPI.sourceLabel(source));
        },

        loadingSources() {
            return ['Semantic Scholar', 'OpenAlex'];
        },

        searchStatusSummary() {
            const filters = this.activeFilters();
            if (filters.length) {
                return `Checking indexed papers for "${this.title()}" with ${filters.join(' and ')}.`;
            }

            return `Checking indexed papers for "${this.title()}" and preparing a gap brief.`;
        },

        paperLink(paper) {
            return paper?.url || paper?.pdf_url || '';
        },

        sourceLabel(source) {
            if (!source) {
                return 'Unknown source';
            }
            return window.searchAPI.sourceLabel(source);
        },

        supportingPapers(gap) {
            return gap?.evidence?.supporting_papers || [];
        },

        scoreLabel(score) {
            return `Score ${Number(score).toFixed(2)}`;
        },

        supportCountLabel(gap) {
            const count = gap?.evidence?.support_count || 0;
            return `${count} supporting paper${count === 1 ? '' : 's'}`;
        },

        recentCountLabel(gap) {
            const count = gap?.evidence?.recent_support_count || 0;
            return `${count} recent`;
        },

        influentialCountLabel(gap) {
            const count = gap?.evidence?.influential_support_count || 0;
            return `${count} influential`;
        },

        supportingPaperMeta(paper) {
            const parts = [];
            if (paper?.venue) {
                parts.push(paper.venue);
            }
            if (paper?.year) {
                parts.push(String(paper.year));
            }
            if (paper?.citation_count) {
                parts.push(`${paper.citation_count} cites`);
            }
            return parts.join(' · ');
        },

        evidenceTags(gap) {
            const evidence = gap?.evidence || {};
            const groups = [
                ['Limitations', evidence.recurring_limitations],
                ['Future work', evidence.recurring_future_work],
                ['Assumptions', evidence.dominant_assumptions],
                ['Missing metrics', evidence.missing_metrics],
                ['Missing datasets', evidence.missing_datasets],
                ['Weak baselines', evidence.weak_baselines],
            ];

            return groups.flatMap(([label, values]) =>
                (values || []).slice(0, 3).map((value) => ({
                    label,
                    value: String(value).replace(/_/g, ' '),
                }))
            );
        },
    }));
});
