document.addEventListener('alpine:init', () => {
    Alpine.data('resultsPage', () => ({
        activeTab: 'map',
        
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

        visualizations() {
            if (this.$store.app.isLoading) {
                return null;
            }
            return this.$store.app.result?.gapData?.visualizations || this.$store.app.result?.searchData?.visualizations || null;
        },

        clusters() {
            if (this.$store.app.isLoading) {
                return [];
            }
            return this.$store.app.result?.gapData?.clusters || this.$store.app.result?.searchData?.clusters || [];
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

        searchStatusSummary() {
            const filters = this.activeFilters();
            const current = this.currentProgressEvent();
            if (filters.length) {
                return `${current.detail} Filters: ${filters.join(' and ')}.`;
            }

            return `${current.detail} Topic: "${this.title()}".`;
        },

        progressEvents() {
            return this.$store.app.progressEvents || [];
        },

        currentProgressEvent() {
            const events = this.progressEvents();
            return events[events.length - 1] || {
                label: 'Starting research',
                detail: 'Connecting to the analysis pipeline.',
                progress: 4,
            };
        },

        loadingProgress() {
            const progress = Math.max(4, Math.min(100, Math.round(this.currentProgressEvent().progress || 4)));
            return progress;
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
            return gap?.citations || [];
        },

        getCitationLink(citation) {
            if (!citation) return null;
            if (citation.url) return citation.url;
            const match = this.papers().find(p => p.title && p.title.toLowerCase() === citation.title.toLowerCase());
            return match ? this.paperLink(match) : null;
        },

        scoreLabel(score) {
            return `Score ${Number(score).toFixed(2)}`;
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
                .map(([key, label]) => ({ label, value: Number(breakdown[key]).toFixed(2) }));
        },

        validationLabel(gap) {
            const validation = gap?.citation_validation || {};
            if (validation.status === 'grounded') {
                return `Citation grounded · ${validation.evidence_snippet_count || 0} evidence snippets`;
            }
            return `Needs review · ${(validation.issues || []).length || 0} checks`;
        },

        supportCountLabel(gap) {
            const count = gap?.citations?.length || gap?.supporting_papers?.length || 0;
            return `${count} supporting paper${count === 1 ? '' : 's'}`;
        },

        recentCountLabel(gap) {
            const count = (gap?.citations || []).filter(c => c.year && c.year >= new Date().getFullYear() - 2).length;
            return `${count} recent`;
        },

        influentialCountLabel(gap) {
            const count = (gap?.citations || []).filter(c => c.citation_count > 10).length;
            return `${count} influential`;
        },

        supportingPaperMeta(paper) {
            const parts = [];
            if (paper?.venue && paper.venue !== "Unknown Venue") {
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
            // Keep for backward compatibility if needed, but we'll use grouped version
            return [];
        },

        hasValue(val) {
            if (val === undefined || val === null) return false;
            // Strip out "undefined" occurrences to catch clumps like "undefined\n\nundefined"
            const cleanStr = String(val).replace(/undefined/gi, '').trim();
            return cleanStr.length > 0 && cleanStr !== 'null';
        },

        getGapField(gap, field) {
            const val = gap ? gap[field] : '';
            return this.hasValue(val) ? val : '';
        },

        renderTextWithCitations(text, gap) {
            if (!this.hasValue(text)) return '';
            text = String(text);
            
            const citations = this.supportingPapers(gap);
            // Replace [n] with clickable links
            return text.replace(/\[(\d+)\]/g, (match, n) => {
                const idx = parseInt(n) - 1;
                const citation = citations[idx];
                const link = this.getCitationLink(citation);
                if (link) {
                    return `<a href="${link}" target="_blank" rel="noopener noreferrer" class="cite-badge" style="vertical-align: baseline; margin: 0 2px; text-decoration: none;">${match}</a>`;
                }
                return match;
            });
        },

        reportId() {
            return this.$store.app.result?.gapData?.report_id || '';
        },

        pdfUrl() {
            const path = this.$store.app.result?.gapData?.pdf_url;
            return path ? `${BASE_URL}${path}` : '';
        },

        shareUrl() {
            const path = this.$store.app.result?.gapData?.share_url;
            return path ? `${window.location.origin}${path}` : '';
        },

        isDownloadingPdf: false,

        async downloadPdf() {
            const path = this.$store.app.result?.gapData?.pdf_url;
            if (!path) {
                alert("PDF not available for this report.");
                return;
            }
            
            if (this.isDownloadingPdf) return;
            this.isDownloadingPdf = true;
            
            try {
                const response = await window.searchAPI.authenticatedFetch(`${BASE_URL}${path}`);
                if (!response.ok) throw new Error("Failed to download PDF.");
                
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `Research_Report_${this.title().substring(0,30).replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);
            } catch (err) {
                console.error("PDF Download error:", err);
                alert("Could not download the full report. Please try again later.");
            } finally {
                this.isDownloadingPdf = false;
            }
        },

        isDownloadingMarkdown: false,

        async downloadMarkdown() {
            const reportId = this.reportId();
            if (!reportId) {
                alert("Markdown export not available for this report.");
                return;
            }
            
            if (this.isDownloadingMarkdown) return;
            this.isDownloadingMarkdown = true;
            
            try {
                // Using the exact route pattern from synthesis.py
                const url = `${BASE_URL}/synthesis/report/${reportId}/markdown`;
                const response = await window.searchAPI.authenticatedFetch(url);
                if (!response.ok) throw new Error("Failed to download Markdown.");
                
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `Synthesis_Report_${this.title().substring(0,30).replace(/[^a-zA-Z0-9]/g, '_')}.md`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);
            } catch (err) {
                console.error("Markdown Download error:", err);
                alert("Could not download the markdown report. Please try again later.");
            } finally {
                this.isDownloadingMarkdown = false;
            }
        },

        isCopied: false,

        async copyToClipboard() {
            const text = this.$store.app.result?.gapData?.copy_text || '';
            if (!text) {
                console.warn('No synthesis text available to copy');
                return;
            }

            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(text);
                } else {
                    // Fallback for non-secure contexts
                    const textArea = document.createElement("textarea");
                    textArea.value = text;
                    textArea.style.position = "fixed";
                    textArea.style.left = "-9999px";
                    textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    document.execCommand('copy');
                    textArea.remove();
                }

                this.isCopied = true;
                setTimeout(() => {
                    this.isCopied = false;
                }, 2000);
            } catch (err) {
                console.error('Failed to copy text: ', err);
                alert('Could not copy to clipboard. Please try manually selecting the text.');
            }
        },

        isLiked: false,
        isDisliked: false,

        toggleLike() {
            this.isLiked = !this.isLiked;
            if (this.isLiked) this.isDisliked = false;
        },

        toggleDislike() {
            this.isDisliked = !this.isDisliked;
            if (this.isDisliked) this.isLiked = false;
        },

        isRefreshing: false,
        async regenerateSynthesis() {
            if (this.isRefreshing) return;
            this.isRefreshing = true;
            try {
                await this.$store.app.runSearch(this.$store.app.form, { 
                    regenerate: true, 
                    allowCached: false, 
                    replaceRoute: true, 
                    saveHistory: false 
                });
            } catch (err) {
                console.error("Regeneration failed:", err);
                alert("Error refreshing report: " + err.message);
            } finally {
                this.isRefreshing = false;
            }
        },

        async copyShareLink() {
            const url = this.shareUrl();
            if (!url) return false;

            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(url);
                } else {
                    // Fallback
                    const textArea = document.createElement("textarea");
                    textArea.value = url;
                    textArea.style.position = "fixed";
                    textArea.style.left = "-9999px";
                    textArea.style.top = "0";
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();
                    document.execCommand('copy');
                    textArea.remove();
                }
                return true;
            } catch (err) {
                console.error('Failed to copy share URL: ', err);
                return false;
            }
        },

        shareOnGmail() {
            const url = this.shareUrl();
            if (!url) return;
            const subject = `Research Report: ${this.title()}`;
            const body = `Check out this research synthesis on "${this.title()}" via Research Agent!\n\nView full report: ${url}`;
            window.open(`https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`, '_blank');
        },

        shareOnWhatsApp() {
            const url = this.shareUrl();
            if (!url) return;
            const text = `Check out this research synthesis on "${this.title()}" via Research Agent!\n\nView full report: ${url}`;
            window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank');
        },
        async nativeShare() {
            const url = this.shareUrl();
            if (!url) return;
            if (navigator.share) {
                try {
                    await navigator.share({
                        title: `Research Report: ${this.title()}`,
                        text: `Analysis and research gaps for ${this.title()}`,
                        url: url
                    });
                } catch (err) {
                    if (err.name !== 'AbortError') {
                        console.error('Error sharing:', err);
                    }
                }
            } else {
                await this.copyShareLink();
                alert('Share link copied to clipboard (native share not supported)');
            }
        },
    }));
});
