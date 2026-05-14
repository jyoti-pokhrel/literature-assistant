(function () {
    // Cluster palette is sourced from CSS custom properties (--c-1..4 in tokens.css).
    // Re-read on demand so theme switches re-paint correctly.
    function readPalette() {
        const root = getComputedStyle(document.documentElement);
        return ['--c-1', '--c-2', '--c-3', '--c-4']
            .map((v) => root.getPropertyValue(v).trim())
            .filter(Boolean);
    }

    let state = null;

    function normalizedTitle(title) {
        return String(title || "").trim().toLowerCase();
    }

    function paperId(paper, fallback = "") {
        return String(paper?.paper_id || paper?.external_id || paper?.url || normalizedTitle(paper?.title) || fallback);
    }

    function colorForCluster(clusterId) {
        const palette = readPalette();
        if (!palette.length) return '#1a1816';
        const index = Math.abs(Number(clusterId) || 0) % palette.length;
        return palette[index];
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function flattenClusters(clusters = []) {
        return clusters.flatMap((cluster) => (cluster.papers || []).map((paper, index) => ({
            ...paper,
            __cluster: cluster,
            __clusterId: cluster.cluster_id,
            __paperId: paperId(paper, `${cluster.cluster_id}-${index}`),
        })));
    }

    function destroy() {
        if (!state) return;
        state.resizeObserver?.disconnect();
        state.tooltip?.remove();
        state.overlay?.remove();
        state.container.innerHTML = "";
        state = null;
    }

    function render(container, clusters = []) {
        if (!container || typeof d3 === "undefined") {
            return null;
        }

        destroy();
        container.innerHTML = "";
        container.style.position = "relative";
        container.style.overflow = "hidden";

        // Create HTML tooltip
        const tooltip = d3.select(document.body)
            .append("div")
            .attr("class", "cluster-map-tooltip premium-tooltip")
            .style("opacity", 0)
            .style("position", "absolute")
            .style("pointer-events", "none")
            .style("z-index", "1000")
            .style("background", "var(--nav-bg)")
            .style("backdrop-filter", "blur(12px)")
            .style("border", "1px solid var(--border-color)")
            .style("border-radius", "12px")
            .style("padding", "12px 16px")
            .style("box-shadow", "var(--shadow-soft)")
            .style("color", "var(--text-main)")
            .style("max-width", "300px")
            .style("transform", "translateY(10px)")
            .style("transition", "opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1), transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)");

        // Overlay zoom controls. Class hooks (cit-canvas-overlay, cit-zoom)
        // are shared with the citation graph so both maps render the same
        // bottom-right pill stack — see citations.css.
        const overlay = d3.select(container)
            .append("div")
            .attr("class", "cit-canvas-overlay cit-zoom")
            .attr("role", "group")
            .attr("aria-label", "Zoom controls");

        const zoom = d3.zoom().scaleExtent([0.5, 8]);

        overlay.append("button")
            .attr("type", "button")
            .attr("title", "Zoom in")
            .attr("aria-label", "Zoom in")
            .html(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>`)
            .on("click", (e) => { e.stopPropagation(); svg.transition().duration(500).call(zoom.scaleBy, 1.5); });

        overlay.append("button")
            .attr("type", "button")
            .attr("title", "Zoom out")
            .attr("aria-label", "Zoom out")
            .html(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line></svg>`)
            .on("click", (e) => { e.stopPropagation(); svg.transition().duration(500).call(zoom.scaleBy, 0.667); });

        overlay.append("button")
            .attr("type", "button")
            .attr("title", "Recenter")
            .attr("aria-label", "Recenter")
            .html(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v3"></path><path d="M12 18v3"></path><path d="M3 12h3"></path><path d="M18 12h3"></path><circle cx="12" cy="12" r="5"></circle></svg>`)
            .on("click", (e) => { e.stopPropagation(); svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity); });

        const svg = d3.select(container)
            .append("svg")
            .attr("class", "cluster-map-svg")
            .style("width", "100%")
            .style("height", "100%");

        // SVG Filters for glow effects
        const defs = svg.append("defs");
        const filter = defs.append("filter").attr("id", "glow").attr("x", "-20%").attr("y", "-20%").attr("width", "140%").attr("height", "140%");
        filter.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
        filter.append("feComposite").attr("in", "SourceGraphic").attr("in2", "blur").attr("operator", "over");

        const root = svg.append("g").attr("class", "cluster-map-root");
        const hullLayer = root.append("g").attr("class", "cluster-map-hulls");
        const pointLayer = root.append("g").attr("class", "cluster-map-points");
        
        const empty = d3.select(container)
            .append("div")
            .attr("class", "cluster-map-empty")
            .style("display", "none")
            .style("position", "absolute")
            .style("inset", "0")
            .style("align-items", "center")
            .style("justify-content", "center")
            .style("color", "var(--text-muted)")
            .style("font-weight", "600")
            .text("No map coordinates available");

        const current = {
            container,
            clusters,
            svg,
            root,
            hullLayer,
            pointLayer,
            tooltip,
            overlay,
            zoom,
            resizeObserver: null,
            points: flattenClusters(clusters),
            selectedPaperIds: new Set(),
            hoveredClusterId: null,
        };

        // Smooth curve generator for hulls
        const lineGenerator = d3.line()
            .curve(d3.curveCatmullRomClosed.alpha(0.5));

        function draw() {
            const width = Math.max(container.clientWidth || 0, 320);
            const height = Math.max(container.clientHeight || 0, 280);
            const points = current.points.filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)));

            svg.attr("viewBox", `0 0 ${width} ${height}`);
            empty.style("display", points.length ? "none" : "flex");

            if (!points.length) {
                hullLayer.selectAll("*").remove();
                pointLayer.selectAll("*").remove();
                return;
            }

            const xExtent = d3.extent(points, (d) => Number(d.x));
            const yExtent = d3.extent(points, (d) => Number(d.y));
            const pad = 60;
            const xScale = d3.scaleLinear()
                .domain(xExtent[0] === xExtent[1] ? [xExtent[0] - 1, xExtent[1] + 1] : xExtent)
                .range([pad, width - pad]);
            const yScale = d3.scaleLinear()
                .domain(yExtent[0] === yExtent[1] ? [yExtent[0] - 1, yExtent[1] + 1] : yExtent)
                .range([height - pad, pad]);

            const hulls = clusters.map((cluster) => {
                const clusterPoints = points
                    .filter((point) => String(point.__clusterId) === String(cluster.cluster_id))
                    .map((point) => [xScale(Number(point.x)), yScale(Number(point.y))]);
                
                let polygon = null;
                if (clusterPoints.length >= 3) {
                    polygon = d3.polygonHull(clusterPoints);
                } else if (clusterPoints.length === 2) {
                    // Create a pseudo-polygon for 2 points to render a blob
                    const [p1, p2] = clusterPoints;
                    const dx = p2[0] - p1[0], dy = p2[1] - p1[1];
                    const norm = Math.sqrt(dx*dx + dy*dy);
                    const nx = -dy/norm * 20, ny = dx/norm * 20;
                    polygon = [
                        [p1[0] + nx, p1[1] + ny],
                        [p2[0] + nx, p2[1] + ny],
                        [p2[0] - nx, p2[1] - ny],
                        [p1[0] - nx, p1[1] - ny]
                    ];
                } else if (clusterPoints.length === 1) {
                    const p = clusterPoints[0];
                    polygon = [
                        [p[0], p[1] - 25],
                        [p[0] + 25, p[1]],
                        [p[0], p[1] + 25],
                        [p[0] - 25, p[1]]
                    ];
                }

                return {
                    cluster,
                    polygon,
                    points: clusterPoints,
                };
            });

            // Smooth Hulls
            hullLayer.selectAll("path.cluster-hull-soft")
                .data(hulls.filter((item) => item.polygon), (d) => d.cluster.cluster_id)
                .join(
                    enter => enter.append("path")
                        .attr("class", "cluster-hull-soft")
                        .attr("opacity", 0)
                        .attr("d", d => lineGenerator(d.polygon))
                        .attr("fill", d => colorForCluster(d.cluster.cluster_id))
                        .attr("stroke", d => colorForCluster(d.cluster.cluster_id))
                        .attr("stroke-width", 1.25)
                        .attr("stroke-opacity", 0.5)
                        .call(e => e.transition("hull-enter").duration(750).attr("opacity", 0.42)),
                    update => {
                        update.transition("hull-update").duration(750).attr("d", d => lineGenerator(d.polygon));
                        return update;
                    },
                    exit => {
                        exit.transition("hull-exit").duration(400).attr("opacity", 0).remove();
                    }
                )
                .on("click", (event, d) => {
                    event.stopPropagation();
                    container.dispatchEvent(new CustomEvent("cluster:select", {
                        bubbles: true,
                        detail: { cluster: d.cluster },
                    }));
                })
                .on("mouseenter", (event, d) => {
                    current.hoveredClusterId = d.cluster.cluster_id;
                    applyHighlight();
                })
                .on("mouseleave", () => {
                    current.hoveredClusterId = null;
                    applyHighlight();
                });

            // Nodes
            pointLayer.selectAll("circle.paper-dot-premium")
                .data(points, (d) => d.__paperId)
                .join(
                    enter => enter.append("circle")
                        .attr("class", "paper-dot-premium")
                        .attr("r", 0)
                        .attr("cx", (d) => xScale(Number(d.x)))
                        .attr("cy", (d) => yScale(Number(d.y)))
                        .attr("fill", (d) => colorForCluster(d.__clusterId))
                        .attr("stroke", "var(--bg-color)")
                        .attr("stroke-width", "1.5px")
                        .attr("data-paper-id", (d) => d.__paperId)
                        .style("cursor", "pointer")
                        .call(e => e.transition("node-enter").duration(750).delay((d, i) => i * 2).attr("r", 7.5)),
                    update => {
                        update.transition("node-update").duration(750)
                            .attr("cx", (d) => xScale(Number(d.x)))
                            .attr("cy", (d) => yScale(Number(d.y)));
                        return update;
                    },
                    exit => {
                        exit.transition("node-exit").duration(400).attr("r", 0).remove();
                    }
                )
                .on("mouseenter", (event, d) => {
                    current.hoveredClusterId = d.__clusterId;
                    applyHighlight();

                    const color = colorForCluster(d.__clusterId);
                    tooltip
                        .style("opacity", 1)
                        .style("transform", "translateY(0)")
                        .html(`
                            <div style="font-size: 0.75rem; color: ${color}; font-weight: 800; text-transform: uppercase; margin-bottom: 4px;">Cluster ${d.__clusterId}</div>
                            <strong style="display: block; font-size: 0.95rem; line-height: 1.3; margin-bottom: 6px;">${escapeHtml(d.title || "Untitled paper")}</strong>
                            <span style="font-size: 0.8rem; color: var(--text-muted); display: block;">${escapeHtml([d.venue, d.year].filter(Boolean).join(" · ") || "Unknown venue")}</span>
                        `);
                    d3.select(event.currentTarget)
                        .transition("node-hover").duration(200)
                        .attr("r", 10)
                        .attr("filter", "url(#glow)");
                })
                .on("mousemove", (event) => {
                    tooltip
                        .style("left", `${event.pageX + 16}px`)
                        .style("top", `${event.pageY + 16}px`);
                })
                .on("mouseleave", (event) => {
                    current.hoveredClusterId = null;
                    applyHighlight();

                    tooltip
                        .style("opacity", 0)
                        .style("transform", "translateY(10px)");
                    d3.select(event.currentTarget)
                        .transition("node-hover").duration(300)
                        .attr("r", 6.5)
                        .attr("filter", null);
                })
                .on("click", (event, d) => {
                    event.stopPropagation();
                    container.dispatchEvent(new CustomEvent("paper:select", {
                        bubbles: true,
                        detail: { paper: d },
                    }));
                });

            applyHighlight();
        }

        function applyHighlight() {
            const selected = current.selectedPaperIds;
            const hoveredCluster = current.hoveredClusterId;
            const hasSelection = selected.size > 0;
            const hasHover = hoveredCluster !== null;

            current.pointLayer.selectAll("circle.paper-dot-premium")
                .transition("node-highlight").duration(300)
                .style("opacity", (d) => {
                    if (hasHover && String(d.__clusterId) !== String(hoveredCluster)) return 0.15;
                    if (hasSelection && !selected.has(d.__paperId) && !selected.has(paperId(d))) return 0.15;
                    return 1;
                })
                .style("filter", (d) => {
                    if (hasSelection && (selected.has(d.__paperId) || selected.has(paperId(d)))) return "url(#glow)";
                    return null;
                });

            current.hullLayer.selectAll("path.cluster-hull-soft")
                .transition("hull-highlight").duration(300)
                .attr("opacity", (d) => {
                    if (hasHover) {
                        return String(d.cluster.cluster_id) === String(hoveredCluster) ? 0.58 : 0.18;
                    }
                    if (hasSelection) {
                        return 0.2;
                    }
                    return 0.42; // default — visible enough to read clusters at a glance
                });
        }

        zoom.on("zoom", (event) => {
            root.attr("transform", event.transform);
        });
        svg.call(zoom);

        svg.on("click", () => {
            container.dispatchEvent(new CustomEvent("map:clear", { bubbles: true }));
        });

        current.resizeObserver = new ResizeObserver(() => {
            // debounced resize
            clearTimeout(current.resizeTimeout);
            current.resizeTimeout = setTimeout(draw, 100);
        });
        current.resizeObserver.observe(container);
        
        current.applyHighlight = applyHighlight;
        
        state = current;
        draw();
        return current;
    }

    function highlightPapers(paperIds = []) {
        if (!state) return;
        state.selectedPaperIds = new Set((paperIds || []).map((id) => String(id)).filter(Boolean));
        state.applyHighlight?.();
    }

    function clearHighlight() {
        highlightPapers([]);
    }

    function repaintFromTokens() {
        if (!state || !state.container) return;
        const clusters = state.clusters || [];
        if (!clusters.length) return;
        render(state.container, clusters);
    }

    window.addEventListener('theme:change', repaintFromTokens);

    window.ClusterMap = {
        render,
        highlightPapers,
        clearHighlight,
        destroy,
        colors: readPalette,
        paperId,
    };
})();
