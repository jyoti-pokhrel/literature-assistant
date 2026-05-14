
(function () {
    'use strict';


    /*  Palette  */


    function readVar(name, fallback = '') {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
    }

    function getPalette() {
        const c1 = readVar('--c-1', '#8b1e1e');
        const c2 = readVar('--c-2', '#b86b3c');
        const c3 = readVar('--c-3', '#c9a75e');
        const c4 = readVar('--c-4', '#1a1816');
        const ink = readVar('--ink', '#1a1816');
        const inkMuted = readVar('--ink-2', '#6b665e');
        return {
            primary: c1,
            primaryDark: c1,
            primaryLight: c2,
            teal: c2,
            tealDark: c2,
            amber: c3,
            rose: c1,
            slate: inkMuted,
            green: c4,
            barGradient: [c1, c2, c3],
            multiBar: [c1, c2, c3, c4, inkMuted, ink],
        };
    }

    const PALETTE_PROXY = new Proxy({}, {
        get(_, key) { return getPalette()[key]; },
    });
    const PALETTE = PALETTE_PROXY;

    function getThemeColors() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            isDark,
            text:        readVar('--ink', isDark ? '#e8e4d8' : '#1a1816'),
            textMuted:   readVar('--ink-2', isDark ? '#8a8378' : '#6b665e'),
            grid:        readVar('--rule', isDark ? 'rgba(232,228,216,0.08)' : 'rgba(26,24,22,0.10)'),
            bg:          readVar('--paper', isDark ? '#0e0d0b' : '#f5f1e8'),
            tooltipBg:   readVar('--paper-2', isDark ? '#16140f' : '#efeadc'),
            tooltipBorder: readVar('--rule-strong', isDark ? 'rgba(232,228,216,0.18)' : 'rgba(26,24,22,0.18)'),
            tooltipText:  readVar('--ink', isDark ? '#e8e4d8' : '#1a1816'),
        };
    }

    /*  Shared helpers  */

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

    /*  1. Confidence Bars  */

    function renderConfidenceBars(container, gaps) {
        if (!container || !gaps || !gaps.length) return;

        const theme = getThemeColors();
        const longestLabel = d3.max(gaps, g => (g.gap_id || '').length);
        const leftMargin = Math.min(Math.max(longestLabel * 7.5, 86), 180);
        const margin = { top: 8, right: 28, bottom: 20, left: leftMargin };
        const barH = 34;
        const gapSize = 8;
        const height = margin.top + margin.bottom + gaps.length * (barH + gapSize);
        const width = 480;
        const { g, innerWidth, innerHeight } = ensureSvg(container, width, height, margin);

        const data = gaps.map((gap, i) => ({
            label: gap.gap_id || `G${i + 1}`,
            score: Number(gap.confidence_score ?? 0),
            title: gap.gap_title || '',
        })).sort((a, b) => b.score - a.score);

        const x = d3.scaleLinear()
            .domain([0, 1])
            .range([0, innerWidth]);

        const y = d3.scaleBand()
            .domain(data.map(d => d.label))
            .range([0, innerHeight])
            .padding(0.18);

        // Grid lines
        g.append('g')
            .attr('class', 'grid-lines')
            .selectAll('line')
            .data(x.ticks(5))
            .join('line')
            .attr('x1', d => x(d)).attr('x2', d => x(d))
            .attr('y1', 0).attr('y2', innerHeight)
            .attr('stroke', theme.grid)
            .attr('stroke-dasharray', '3,3');

        // Axes
        const xAxis = g.append('g')
            .attr('transform', `translate(0,${innerHeight})`)
            .call(d3.axisBottom(x).ticks(5).tickFormat(d3.format('.1f')).tickSize(0).tickPadding(8));

        addAxisStyles(g, theme);
        xAxis.selectAll('.tick line').attr('stroke', 'none');

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
            .attr('height', y.bandwidth())
            .attr('rx', 5)
            .attr('fill', theme.text)
            .attr('fill-opacity', d => {
                const t = Math.max(0, Math.min(1, d.score));
                return (0.55 + 0.4 * t).toFixed(2);
            })
            .attr('width', 0)
            .style('cursor', 'pointer')
            .on('mouseenter', function (event, d) {
                d3.select(this).attr('fill-opacity', 1);
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.title ? d.title + '<br/>' : ''}Score: ${d.score.toFixed(2)}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.title ? d.title + '<br/>' : ''}Score: ${d.score.toFixed(2)}`, container);
            })
            .on('mouseleave', function (event, d) {
                const t = Math.max(0, Math.min(1, d.score));
                d3.select(this).attr('fill-opacity', (0.55 + 0.4 * t).toFixed(2));
                hideTip(tip);
            })
            .transition()
            .duration(600)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 45)
            .attr('width', d => x(d.score));

        // Score labels after bars
        g.selectAll('.val-label')
            .data(data)
            .join('text')
            .attr('class', 'val-label')
            .attr('x', d => x(d.score) + 6)
            .attr('y', d => y(d.label) + y.bandwidth() / 2)
            .attr('dy', '0.35em')
            .attr('fill', theme.text)
            .style('font-size', '0.72rem')
            .style('font-weight', '700')
            .style('font-family', "'Manrope', sans-serif")
            .style('opacity', 0)
            .text(d => d.score.toFixed(2))
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
            .text(d => d.label);
    }

    /*  2. Year Distribution */

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
                d3.select(this).attr('fill-opacity', 1);
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} paper${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.year}</strong><br/>${d.count} paper${d.count === 1 ? '' : 's'}`, container);
            })
            .on('mouseleave', function (event, d) {
                const t = Math.max(0, Math.min(1, d.score));
                d3.select(this).attr('fill-opacity', (0.55 + 0.4 * t).toFixed(2));
                hideTip(tip);
            })
            .transition()
            .duration(600)
            .ease(d3.easeCubicOut)
            .delay((_, i) => i * 50)
            .attr('y', d => y(d.count))
            .attr('height', d => innerHeight - y(d.count));
    }


    /*  3. Cluster Size */

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
                d3.select(this).attr('fill-opacity', 1);
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.value} paper${d.value === 1 ? '' : 's'}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>${d.value} paper${d.value === 1 ? '' : 's'}`, container);
            })
            .on('mouseleave', function (event, d) {
                const t = Math.max(0, Math.min(1, d.score));
                d3.select(this).attr('fill-opacity', (0.55 + 0.4 * t).toFixed(2));
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

    /*  4. Method Trends  */


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

 
    /*  5 & 6. Frequency horizontal bars (dataset / metric)  */


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
                d3.select(this).attr('fill-opacity', 1);
                showTip(tip, event, `<strong>${d.label}</strong><br/>Count: ${d.value}`, container);
            })
            .on('mousemove', function (event, d) {
                showTip(tip, event, `<strong>${d.label}</strong><br/>Count: ${d.value}`, container);
            })
            .on('mouseleave', function (event, d) {
                const t = Math.max(0, Math.min(1, d.score));
                d3.select(this).attr('fill-opacity', (0.55 + 0.4 * t).toFixed(2));
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

    /*  1b. Gap Confidence Spider (single selected gap, multi-axis)  */

    function renderConfidenceSpider(container, gap) {
        if (!container) return;
        d3.select(container).selectAll('*').remove();
        if (!gap) return;

        const theme = getThemeColors();
        const axes = [
            { key: 'novelty',             label: 'Novelty' },
            { key: 'support',             label: 'Support' },
            { key: 'severity',            label: 'Severity' },
            { key: 'actionability',       label: 'Actionable' },
            { key: 'citation_confidence', label: 'Citation' },
        ];

        const breakdown = gap.score_breakdown || {};
        const data = axes
            .filter(a => breakdown[a.key] !== undefined && breakdown[a.key] !== null)
            .map(a => ({
                ...a,
                value: Math.max(0, Math.min(1, Number(breakdown[a.key]) || 0)),
            }));

        // Fewer than 3 axes — fall back to a single confidence ring so the
        // panel never looks broken on gaps with sparse breakdowns.
        if (data.length < 3) {
            renderConfidenceRing(container, gap);
            return;
        }

        const size = 360;
        const padding = 56;
        const radius = (size - padding * 2) / 2;
        const cx = size / 2;
        const cy = size / 2;

        const svg = d3.select(container).append('svg')
            .attr('viewBox', `0 0 ${size} ${size}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .style('width', '100%')
            .style('height', 'auto')
            .style('display', 'block')
            .style('overflow', 'visible');

        const root = svg.append('g').attr('transform', `translate(${cx},${cy})`);
        const angleSlice = (Math.PI * 2) / data.length;
        const levels = [0.25, 0.5, 0.75, 1.0];

        // Concentric polygons (matching the data polygon shape, not circles)
        levels.forEach((level, idx) => {
            const ringPoints = data.map((_, i) => {
                const angle = angleSlice * i - Math.PI / 2;
                return [Math.cos(angle) * radius * level, Math.sin(angle) * radius * level];
            });
            root.append('path')
                .attr('d', d3.line().curve(d3.curveLinearClosed)(ringPoints))
                .attr('fill', 'none')
                .attr('stroke', theme.grid)
                .attr('stroke-width', level === 1 ? 1 : 0.8)
                .attr('stroke-dasharray', level === 1 ? 'none' : '2 4');
        });

        // Axis spokes + outer labels
        data.forEach((d, i) => {
            const angle = angleSlice * i - Math.PI / 2;
            const x = Math.cos(angle) * radius;
            const y = Math.sin(angle) * radius;

            root.append('line')
                .attr('x1', 0).attr('y1', 0)
                .attr('x2', x).attr('y2', y)
                .attr('stroke', theme.grid)
                .attr('stroke-width', 0.7);

            const labelOffset = 18;
            const lx = Math.cos(angle) * (radius + labelOffset);
            const ly = Math.sin(angle) * (radius + labelOffset);

            let anchor = 'middle';
            if (lx > 4) anchor = 'start';
            else if (lx < -4) anchor = 'end';

            let dy = '0.35em';
            if (ly < -8) dy = '0';
            else if (ly > 8) dy = '0.85em';

            root.append('text')
                .attr('x', lx)
                .attr('y', ly)
                .attr('text-anchor', anchor)
                .attr('dy', dy)
                .attr('fill', theme.textMuted)
                .style('font-size', '0.7rem')
                .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
                .style('font-weight', '600')
                .style('letter-spacing', '0.08em')
                .style('text-transform', 'uppercase')
                .text(d.label);
        });

        // Level tick labels along the top spoke
        levels.forEach(level => {
            if (level === 0.25) return;
            root.append('text')
                .attr('x', 4)
                .attr('y', -radius * level + 3)
                .attr('fill', theme.textMuted)
                .style('font-size', '0.6rem')
                .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
                .style('opacity', 0.55)
                .text(level.toFixed(2));
        });

        // The data polygon
        const polyPoints = data.map((d, i) => {
            const angle = angleSlice * i - Math.PI / 2;
            return [Math.cos(angle) * radius * d.value, Math.sin(angle) * radius * d.value];
        });

        const polyPath = root.append('path')
            .attr('d', d3.line().curve(d3.curveLinearClosed)(polyPoints))
            .attr('fill', theme.text)
            .attr('fill-opacity', 0)
            .attr('stroke', theme.text)
            .attr('stroke-width', 1.8)
            .attr('stroke-linejoin', 'round')
            .attr('stroke-opacity', 0);

        polyPath
            .transition()
            .duration(520)
            .ease(d3.easeCubicOut)
            .attr('fill-opacity', 0.14)
            .attr('stroke-opacity', 0.9);

        // Vertex dots, sized + opacity by value
        polyPoints.forEach((p, i) => {
            root.append('circle')
                .attr('cx', p[0])
                .attr('cy', p[1])
                .attr('r', 3.5)
                .attr('fill', theme.text)
                .attr('fill-opacity', 0)
                .transition()
                .duration(360)
                .delay(280 + i * 60)
                .attr('fill-opacity', 0.55 + 0.4 * data[i].value);
        });

        // Score readouts just outside each vertex
        const tip = addTooltip(container);
        styleTooltip(tip, theme);

        polyPoints.forEach((p, i) => {
            const angle = angleSlice * i - Math.PI / 2;
            const readoutMag = 12;
            const rx = p[0] + Math.cos(angle) * readoutMag;
            const ry = p[1] + Math.sin(angle) * readoutMag;

            root.append('text')
                .attr('x', rx)
                .attr('y', ry)
                .attr('text-anchor', 'middle')
                .attr('dy', '0.35em')
                .attr('fill', theme.text)
                .style('font-size', '0.7rem')
                .style('font-weight', '600')
                .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
                .style('opacity', 0)
                .text(data[i].value.toFixed(2))
                .transition()
                .duration(360)
                .delay(420 + i * 60)
                .style('opacity', 1);
        });

        // Overall confidence number in the center
        const overall = Number(gap.confidence_score ?? 0);
        const centerGroup = root.append('g').style('opacity', 0);

        centerGroup.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '-0.1em')
            .attr('fill', theme.text)
            .style('font-size', '1.4rem')
            .style('font-weight', '700')
            .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
            .style('letter-spacing', '-0.02em')
            .text(overall.toFixed(2));

        centerGroup.append('text')
            .attr('text-anchor', 'middle')
            .attr('dy', '1.1em')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.62rem')
            .style('font-weight', '600')
            .style('letter-spacing', '0.14em')
            .style('text-transform', 'uppercase')
            .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
            .text('Confidence');

        centerGroup
            .transition()
            .duration(420)
            .delay(680)
            .style('opacity', 1);
    }

    function renderConfidenceRing(container, gap) {
        if (!container || !gap) return;
        const theme = getThemeColors();
        const score = Math.max(0, Math.min(1, Number(gap.confidence_score ?? 0)));
        const size = 240;
        const stroke = 14;
        const r = (size - stroke) / 2;
        const c = 2 * Math.PI * r;

        d3.select(container).selectAll('*').remove();
        const svg = d3.select(container).append('svg')
            .attr('viewBox', `0 0 ${size} ${size}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .style('width', '100%')
            .style('height', 'auto')
            .style('display', 'block');

        const g = svg.append('g').attr('transform', `translate(${size / 2},${size / 2}) rotate(-90)`);

        g.append('circle').attr('r', r).attr('fill', 'none').attr('stroke', theme.grid).attr('stroke-width', stroke);

        g.append('circle')
            .attr('r', r)
            .attr('fill', 'none')
            .attr('stroke', theme.text)
            .attr('stroke-width', stroke)
            .attr('stroke-linecap', 'round')
            .attr('stroke-dasharray', `${c} ${c}`)
            .attr('stroke-dashoffset', c)
            .transition()
            .duration(720)
            .ease(d3.easeCubicOut)
            .attr('stroke-dashoffset', c * (1 - score));

        svg.append('text')
            .attr('x', size / 2).attr('y', size / 2 - 4)
            .attr('text-anchor', 'middle')
            .attr('fill', theme.text)
            .style('font-size', '1.6rem')
            .style('font-weight', '700')
            .style('font-family', "'Plus Jakarta Sans', 'Manrope', sans-serif")
            .style('letter-spacing', '-0.02em')
            .text(score.toFixed(2));

        svg.append('text')
            .attr('x', size / 2).attr('y', size / 2 + 18)
            .attr('text-anchor', 'middle')
            .attr('fill', theme.textMuted)
            .style('font-size', '0.62rem')
            .style('font-weight', '600')
            .style('letter-spacing', '0.14em')
            .style('text-transform', 'uppercase')
            .text('Confidence');
    }

    /*  Public API */
 
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
                const focusGap = data.selectedGap
                    || gaps.slice().sort((a, b) => Number(b.confidence_score ?? 0) - Number(a.confidence_score ?? 0))[0]
                    || gaps[0];
                renderConfidenceSpider(containers.confidenceBars, focusGap);
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
        renderConfidenceSpider,
        renderConfidenceRing,
        renderYearDistribution,
        renderClusterSizes,
        renderMethodTrends,
        renderDatasetFrequency: (c, d) => renderFrequencyBars(c, d, PALETTE.primary),
        renderMetricFrequency: (c, d) => renderFrequencyBars(c, d, PALETTE.teal),
    };
})();
