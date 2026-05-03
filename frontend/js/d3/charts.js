/**
 * FrontendCharts — D3-based chart rendering for gap detection results.
 *
 * Charts rendered:
 *   1. Confidence Bars    — vertical bar chart of gap confidence scores
 *   2. Year Distribution  — bar chart of papers per year
 *   3. Cluster Size       — horizontal bar chart of papers per cluster
 *   4. Method Trends      — area + line chart of method mentions by year
 *   5. Dataset Frequency  — horizontal bar chart of top datasets
 *   6. Metric Frequency   — horizontal bar chart of top metrics
 *
 * Usage:
 *   window.FrontendCharts.renderAll(containers, data)
 */
(function () {
    'use strict';

    /* ------------------------------------------------------------------ */
    /*  Palette                                                           */
    /* ------------------------------------------------------------------ */

    const PALETTE = {
        primary: '#4e79a7',
        primaryDark: '#3f638c',
        primaryLight: '#76b7b2',
        teal: '#76b7b2',
        tealDark: '#4f9a94',
        amber: '#edc949',
        rose: '#e15759',
        slate: '#9ca3af',
        green: '#59a14f',
        barGradient: ['#4e79a7', '#76b7b2', '#59a14f'],
        multiBar: ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ab'],
    };

    function getThemeColors() {
        const isDark = !document.documentElement.hasAttribute('data-theme') ||
            document.documentElement.getAttribute('data-theme') !== 'light';
        return {
            isDark,
            text: isDark ? '#e2e8f0' : '#1e293b',
            textMuted: isDark ? '#94a3b8' : '#64748b',
            grid: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
            bg: isDark ? '#121214' : '#fffdf9',
            tooltipBg: isDark ? 'rgba(15,15,20,0.92)' : 'rgba(255,255,255,0.95)',
            tooltipBorder: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
            tooltipText: isDark ? '#f1f5f9' : '#0f172a',
        };
    }

    /* ------------------------------------------------------------------ */
    /*  Shared helpers                                                    */
    /* ------------------------------------------------------------------ */

    function ensureSvg(container, width, height, margin) {
        d3.select(container).selectAll('*').remove();
        const svg = d3.select(container)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', `0 0 ${width} ${height}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .style('width', '100%')
            .style('height', 'auto')
            .style('overflow', 'visible');

        const g = svg.append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        return {
            svg,
            g,
            innerWidth: width - margin.left - margin.right,
            innerHeight: height - margin.top - margin.bottom,
        };
    }

    function addTooltip(container) {
        let tip = d3.select(container).select('.d3-tooltip');
        if (tip.empty()) {
            tip = d3.select(container)
                .append('div')
                .attr('class', 'd3-tooltip')
                .style('position', 'absolute')
                .style('pointer-events', 'none')
                .style('opacity', 0)
                .style('transition', 'opacity 0.15s ease');
        }
        return tip;
    }

    function styleTooltip(tip, theme) {
        tip.style('background', theme.tooltipBg)
            .style('backdrop-filter', 'blur(12px)')
            .style('-webkit-backdrop-filter', 'blur(12px)')
            .style('border', `1px solid ${theme.tooltipBorder}`)
            .style('border-radius', '8px')
            .style('padding', '8px 12px')
            .style('font-size', '0.8rem')
            .style('font-weight', '600')
            .style('color', theme.tooltipText)
            .style('box-shadow', '0 4px 12px rgba(0,0,0,0.2)')
            .style('white-space', 'nowrap')
            .style('z-index', '10');
    }

    function showTip(tip, event, html, container) {
        const rect = container.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        tip.html(html)
            .style('left', `${x + 12}px`)
            .style('top', `${y - 8}px`)
            .style('opacity', 1);
    }

    function hideTip(tip) {
        tip.style('opacity', 0);
    }

    function addAxisStyles(g, theme) {
        g.selectAll('.domain').attr('stroke', theme.grid);
        g.selectAll('.tick line').attr('stroke', theme.grid);
        g.selectAll('.tick text')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.72rem')
            .style('font-family', "'Manrope', sans-serif");
    }

    /* ------------------------------------------------------------------ */
    /*  1. Confidence Bars                                                */
    /* ------------------------------------------------------------------ */

    function renderConfidenceBars(container, gaps) {
        if (!container || !gaps || !gaps.length) return;

        const theme = getThemeColors();
        const margin = { top: 12, right: 16, bottom: 40, left: 44 };
        const width = 480;
        const height = 260;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const data = gaps.map((gap, i) => ({
            label: gap.gap_id || `G${i + 1}`,
            score: Number(gap.confidence_score ?? 0),
            title: gap.gap_title || '',
        }));

        const x = d3.scaleBand()
            .domain(data.map(d => d.label))
            .range([0, innerWidth])
            .padding(0.32);

        const y = d3.scaleLinear()
            .domain([0, 1])
            .range([innerHeight, 0]);

        // Grid lines
        g.append('g')
            .attr('class', 'grid-lines')
            .selectAll('line')
            .data(y.ticks(5))
            .join('line')
            .attr('x1', 0).attr('x2', innerWidth)
            .attr('y1', d => y(d)).attr('y2', d => y(d))
            .attr('stroke', theme.grid)
            .attr('stroke-dasharray', '3,3');

        // Axes
        const xAxis = g.append('g')
            .attr('transform', `translate(0,${innerHeight})`)
            .call(d3.axisBottom(x).tickSize(0).tickPadding(8));

        const yAxis = g.append('g')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('.1f')).tickSize(-innerWidth).tickPadding(6));

        addAxisStyles(g, theme);
        yAxis.selectAll('.tick line').attr('stroke', 'none');

        // Y label
        g.append('text')
            .attr('transform', 'rotate(-90)')
            .attr('x', -innerHeight / 2)
            .attr('y', -34)
            .attr('text-anchor', 'middle')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.72rem')
            .style('font-family', "'Manrope', sans-serif")
            .text('Confidence');

        // Tooltip
        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        // Bars
        g.selectAll('.bar')
            .data(data)
            .join('rect')
            .attr('class', 'bar')
            .attr('x', d => x(d.label))
            .attr('width', x.bandwidth())
            .attr('y', innerHeight)
            .attr('height', 0)
            .attr('rx', 4)
            .attr('fill', (d, i) => PALETTE.multiBar[i % PALETTE.multiBar.length])
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).attr('opacity', 0.82);
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.title ? d.title + '<br/>' : ''}Score: ${d.score.toFixed(2)}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.title ? d.title + '<br/>' : ''}Score: ${d.score.toFixed(2)}`, container);
            })
            .on('mouseleave', function () {
                d3.select(this).attr('opacity', 1);
                hideTip(tip);
            })
            .transition()
            .duration(600)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 60)
            .attr('y', d => y(d.score))
            .attr('height', d => innerHeight - y(d.score));

        // Score labels above bars
        g.selectAll('.bar-label')
            .data(data)
            .join('text')
            .attr('class', 'bar-label')
            .attr('x', d => x(d.label) + x.bandwidth() / 2)
            .attr('y', d => y(d.score) - 6)
            .attr('text-anchor', 'middle')
            .attr('fill', theme.text)
            .style('font-size', '0.7rem')
            .style('font-weight', '700')
            .style('font-family', "'Manrope', sans-serif")
            .style('opacity', 0)
            .text(d => d.score.toFixed(2))
            .transition()
            .duration(400)
            .delay((_, i) => 400 + i * 60)
            .style('opacity', 1);
    }

    /* ------------------------------------------------------------------ */
    /*  2. Year Distribution                                              */
    /* ------------------------------------------------------------------ */

    function renderYearDistribution(container, papers) {
        if (!container || !papers || !papers.length) return;

        const yearCounts = {};
        papers.forEach(p => {
            const y = parseInt(p.year);
            if (y && y > 1900 && y < 2100) {
                yearCounts[y] = (yearCounts[y] || 0) + 1;
            }
        });

        const data = Object.entries(yearCounts)
            .map(([year, count]) => ({ year: String(year), count }))
            .sort((a, b) => a.year.localeCompare(b.year));

        if (!data.length) return;

        const theme = getThemeColors();
        const margin = { top: 12, right: 16, bottom: 40, left: 40 };
        const width = 480;
        const height = 220;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const x = d3.scaleBand()
            .domain(data.map(d => d.year))
            .range([0, innerWidth])
            .padding(0.28);

        const maxCount = d3.max(data, d => d.count);
        const y = d3.scaleLinear()
            .domain([0, maxCount + 1])
            .range([innerHeight, 0]);

        // Grid
        g.append('g')
            .selectAll('line')
            .data(y.ticks(Math.min(maxCount + 1, 6)))
            .join('line')
            .attr('x1', 0).attr('x2', innerWidth)
            .attr('y1', d => y(d)).attr('y2', d => y(d))
            .attr('stroke', theme.grid)
            .attr('stroke-dasharray', '3,3');

        // Axes
        g.append('g')
            .attr('transform', `translate(0,${innerHeight})`)
            .call(d3.axisBottom(x).tickSize(0).tickPadding(8));

        g.append('g')
            .call(d3.axisLeft(y).ticks(Math.min(maxCount + 1, 6)).tickFormat(d3.format('d')).tickSize(0).tickPadding(6));

        addAxisStyles(g, theme);

        // Y label
        g.append('text')
            .attr('transform', 'rotate(-90)')
            .attr('x', -innerHeight / 2)
            .attr('y', -30)
            .attr('text-anchor', 'middle')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.72rem')
            .style('font-family', "'Manrope', sans-serif")
            .text('Papers');

        // Tooltip
        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        // Bars
        g.selectAll('.bar')
            .data(data)
            .join('rect')
            .attr('class', 'bar')
            .attr('x', d => x(d.year))
            .attr('width', x.bandwidth())
            .attr('y', innerHeight)
            .attr('height', 0)
            .attr('rx', 4)
            .attr('fill', PALETTE.primary)
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).attr('opacity', 0.82);
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} paper${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} paper${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mouseleave', function () {
                d3.select(this).attr('opacity', 1);
                hideTip(tip);
            })
            .transition()
            .duration(600)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 50)
            .attr('y', d => y(d.count))
            .attr('height', d => innerHeight - y(d.count));
    }

    /* ------------------------------------------------------------------ */
    /*  3. Cluster Size                                                   */
    /* ------------------------------------------------------------------ */

    function renderClusterSizes(container, clusters) {
        if (!container || !clusters || !clusters.length) return;

        const data = clusters
            .map((cluster) => ({
                label: `Cluster ${cluster.cluster_id}`,
                value: Number(cluster.paper_count || cluster.papers?.length || 0),
                clusterId: cluster.cluster_id,
            }))
            .filter((item) => item.value > 0)
            .sort((a, b) => b.value - a.value);

        if (!data.length) return;

        const theme = getThemeColors();
        const margin = { top: 8, right: 28, bottom: 14, left: 86 };
        const barH = 28;
        const gap = 7;
        const height = margin.top + margin.bottom + data.length * (barH + gap);
        const width = 480;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const x = d3.scaleLinear()
            .domain([0, d3.max(data, d => d.value)])
            .range([0, innerWidth]);

        const y = d3.scaleBand()
            .domain(data.map(d => d.label))
            .range([0, innerHeight])
            .padding(0.18);

        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        g.selectAll('.bar')
            .data(data)
            .join('rect')
            .attr('class', 'bar')
            .attr('x', 0)
            .attr('y', d => y(d.label))
            .attr('width', 0)
            .attr('height', y.bandwidth())
            .attr('rx', 5)
            .attr('fill', (d, i) => PALETTE.multiBar[i % PALETTE.multiBar.length])
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).attr('opacity', 0.82);
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.value} paper${d.value === 1 ? '' : 's'}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.value} paper${d.value === 1 ? '' : 's'}`, container);
            })
            .on('mouseleave', function () {
                d3.select(this).attr('opacity', 1);
                hideTip(tip);
            })
            .transition()
            .duration(560)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 45)
            .attr('width', d => x(d.value));

        g.selectAll('.val-label')
            .data(data)
            .join('text')
            .attr('class', 'val-label')
            .attr('x', d => x(d.value) + 6)
            .attr('y', d => y(d.label) + y.bandwidth() / 2)
            .attr('dy', '0.35em')
            .attr('fill', theme.text)
            .style('font-size', '0.72rem')
            .style('font-weight', '700')
            .style('font-family', "'Manrope', sans-serif")
            .text(d => d.value);

        g.selectAll('.y-label')
            .data(data)
            .join('text')
            .attr('class', 'y-label')
            .attr('x', -8)
            .attr('y', d => y(d.label) + y.bandwidth() / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', 'end')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.74rem')
            .style('font-family', "'Manrope', sans-serif")
            .text(d => d.label);
    }

    /* ------------------------------------------------------------------ */
    /*  4. Method Trends                                                  */
    /* ------------------------------------------------------------------ */

    function renderMethodTrends(container, methodTrendByYear) {
        if (!container || !methodTrendByYear) return;

        const data = Object.entries(methodTrendByYear)
            .map(([year, methods]) => ({ year: String(year), count: Array.isArray(methods) ? methods.length : 0 }))
            .sort((a, b) => a.year.localeCompare(b.year));

        if (!data.length || data.every(d => d.count === 0)) return;

        const theme = getThemeColors();
        const margin = { top: 12, right: 16, bottom: 40, left: 40 };
        const width = 480;
        const height = 220;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const x = d3.scalePoint()
            .domain(data.map(d => d.year))
            .range([0, innerWidth])
            .padding(0.4);

        const maxCount = d3.max(data, d => d.count);
        const y = d3.scaleLinear()
            .domain([0, maxCount + 1])
            .range([innerHeight, 0]);

        // Grid
        g.append('g')
            .selectAll('line')
            .data(y.ticks(5))
            .join('line')
            .attr('x1', 0).attr('x2', innerWidth)
            .attr('y1', d => y(d)).attr('y2', d => y(d))
            .attr('stroke', theme.grid)
            .attr('stroke-dasharray', '3,3');

        // Axes
        g.append('g')
            .attr('transform', `translate(0,${innerHeight})`)
            .call(d3.axisBottom(x).tickSize(0).tickPadding(8));

        g.append('g')
            .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format('d')).tickSize(0).tickPadding(6));

        addAxisStyles(g, theme);

        // Area
        const area = d3.area()
            .x(d => x(d.year))
            .y0(innerHeight)
            .y1(d => y(d.count))
            .curve(d3.curveMonotoneX);

        const areaGradientId = 'method-area-grad';
        const defs = g.append('defs');
        const areaGrad = defs.append('linearGradient')
            .attr('id', areaGradientId)
            .attr('x1', '0%').attr('y1', '0%')
            .attr('x2', '0%').attr('y2', '100%');
        areaGrad.append('stop').attr('offset', '0%').attr('stop-color', PALETTE.teal).attr('stop-opacity', 0.28);
        areaGrad.append('stop').attr('offset', '100%').attr('stop-color', PALETTE.teal).attr('stop-opacity', 0.02);

        g.append('path')
            .datum(data)
            .attr('fill', `url(#${areaGradientId})`)
            .attr('d', area)
            .style('opacity', 0)
            .transition()
            .duration(700)
            .style('opacity', 1);

        // Line
        const line = d3.line()
            .x(d => x(d.year))
            .y(d => y(d.count))
            .curve(d3.curveMonotoneX);

        const path = g.append('path')
            .datum(data)
            .attr('fill', 'none')
            .attr('stroke', PALETTE.teal)
            .attr('stroke-width', 2.5)
            .attr('stroke-linecap', 'round')
            .attr('d', line);

        const pathLength = path.node().getTotalLength();
        path.attr('stroke-dasharray', `${pathLength} ${pathLength}`)
            .attr('stroke-dashoffset', pathLength)
            .transition()
            .duration(900)
            .ease(d3.easeCubicOut)
            .attr('stroke-dashoffset', 0);

        // Tooltip
        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        // Dots
        g.selectAll('.dot')
            .data(data)
            .join('circle')
            .attr('class', 'dot')
            .attr('cx', d => x(d.year))
            .attr('cy', d => y(d.count))
            .attr('r', 0)
            .attr('fill', PALETTE.tealDark)
            .attr('stroke', theme.bg)
            .attr('stroke-width', 2)
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).transition().duration(150).attr('r', 6);
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} method${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} method${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mouseleave', function () {
                d3.select(this).transition().duration(150).attr('r', 4);
                hideTip(tip);
            })
            .transition()
            .duration(400)
            .delay((_, i) => 600 + i * 60)
            .attr('r', 4);
    }

    /* ------------------------------------------------------------------ */
    /*  5 & 6. Frequency horizontal bars (dataset / metric)               */
    /* ------------------------------------------------------------------ */

    function renderFrequencyBars(container, freqData, color) {
        if (!container || !freqData) return;

        const entries = Object.entries(freqData)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10);

        if (!entries.length) return;

        const data = entries.map(([label, value]) => ({ label, value }));

        const theme = getThemeColors();
        const longestLabel = d3.max(data, d => d.label.length);
        const leftMargin = Math.min(Math.max(longestLabel * 6.5, 80), 180);
        const margin = { top: 8, right: 24, bottom: 12, left: leftMargin };
        const barH = 28;
        const gap = 6;
        const height = margin.top + margin.bottom + data.length * (barH + gap);
        const width = 480;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const x = d3.scaleLinear()
            .domain([0, d3.max(data, d => d.value)])
            .range([0, innerWidth]);

        const y = d3.scaleBand()
            .domain(data.map(d => d.label))
            .range([0, innerHeight])
            .padding(0.18);

        // Tooltip
        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        // Bars
        g.selectAll('.bar')
            .data(data)
            .join('rect')
            .attr('class', 'bar')
            .attr('x', 0)
            .attr('y', d => y(d.label))
            .attr('width', 0)
            .attr('height', y.bandwidth())
            .attr('rx', 4)
            .attr('fill', color || PALETTE.primary)
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).attr('opacity', 0.82);
                showTip(tip, event, `<strong>${d.label}</strong><br/>Count: ${d.value}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>Count: ${d.value}`, container);
            })
            .on('mouseleave', function () {
                d3.select(this).attr('opacity', 1);
                hideTip(tip);
            })
            .transition()
            .duration(600)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 45)
            .attr('width', d => x(d.value));

        // Value labels
        g.selectAll('.val-label')
            .data(data)
            .join('text')
            .attr('class', 'val-label')
            .attr('x', d => x(d.value) + 6)
            .attr('y', d => y(d.label) + y.bandwidth() / 2)
            .attr('dy', '0.35em')
            .attr('fill', theme.text)
            .style('font-size', '0.72rem')
            .style('font-weight', '700')
            .style('font-family', "'Manrope', sans-serif")
            .style('opacity', 0)
            .text(d => d.value)
            .transition()
            .duration(400)
            .delay((_, i) => 400 + i * 45)
            .style('opacity', 1);

        // Y labels
        g.selectAll('.y-label')
            .data(data)
            .join('text')
            .attr('class', 'y-label')
            .attr('x', -8)
            .attr('y', d => y(d.label) + y.bandwidth() / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', 'end')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.74rem')
            .style('font-family', "'Manrope', sans-serif")
            .text(d => d.label.length > 22 ? d.label.slice(0, 20) + '…' : d.label);
    }

    /* ------------------------------------------------------------------ */
    /*  Public API                                                        */
    /* ------------------------------------------------------------------ */

    window.FrontendCharts = {
        /**
         * Render all charts into the provided container refs.
         *
         * @param {Object} containers  — { confidenceBars, yearDist, clusterSizes, methodTrends, datasetFreq, metricFreq }
         * @param {Object} data        — { gaps, papers, clusters, patternAnalysis }
         */
        renderAll(containers, data) {
            if (!containers || !data) return;

            const { gaps, papers, clusters, patternAnalysis } = data;

            if (containers.confidenceBars && gaps?.length) {
                renderConfidenceBars(containers.confidenceBars, gaps);
            }

            if (containers.yearDist && papers?.length) {
                renderYearDistribution(containers.yearDist, papers);
            }

            if (containers.clusterSizes && clusters?.length) {
                renderClusterSizes(containers.clusterSizes, clusters);
            }

            if (containers.methodTrends && patternAnalysis?.method_trend_by_year) {
                renderMethodTrends(containers.methodTrends, patternAnalysis.method_trend_by_year);
            }

            if (containers.datasetFreq && patternAnalysis?.dataset_frequency) {
                renderFrequencyBars(containers.datasetFreq, patternAnalysis.dataset_frequency, PALETTE.primary);
            }

            if (containers.metricFreq && patternAnalysis?.metric_frequency) {
                renderFrequencyBars(containers.metricFreq, patternAnalysis.metric_frequency, PALETTE.teal);
            }
        },

        /** Re-render a single chart. */
        renderConfidenceBars,
        renderYearDistribution,
        renderClusterSizes,
        renderMethodTrends,
        renderDatasetFrequency: (c, d) => renderFrequencyBars(c, d, PALETTE.primary),
        renderMetricFrequency: (c, d) => renderFrequencyBars(c, d, PALETTE.teal),
    };
})();
