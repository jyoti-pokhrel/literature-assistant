(function () {
    const TABLEAU_10 = [
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#59a14f",
        "#edc949",
        "#af7aa1",
        "#ff9da7",
        "#9c755f",
        "#bab0ab",
    ];

    let state = null;

    function normalizedTitle(title) {
        return String(title || "").trim().toLowerCase();
    }

    function paperId(paper, fallback = "") {
        return String(paper?.paper_id || paper?.external_id || paper?.url || normalizedTitle(paper?.title) || fallback);
    }

    function colorForCluster(clusterId) {
        const index = Math.abs(Number(clusterId) || 0) % TABLEAU_10.length;
        return TABLEAU_10[index];
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
        state.container.innerHTML = "";
        state = null;
    }

    function render(container, clusters = []) {
        if (!container || typeof d3 === "undefined") {
            return null;
        }

        destroy();
        container.innerHTML = "";

        const tooltip = d3.select(document.body)
            .append("div")
            .attr("class", "cluster-map-tooltip")
            .style("opacity", 0);

        const svg = d3.select(container)
            .append("svg")
            .attr("class", "cluster-map-svg")
            .attr("role", "img")
            .attr("aria-label", "Interactive UMAP cluster map");

        const root = svg.append("g").attr("class", "cluster-map-root");
        const hullLayer = root.append("g").attr("class", "cluster-map-hulls");
        const pointLayer = root.append("g").attr("class", "cluster-map-points");
        const empty = d3.select(container)
            .append("div")
            .attr("class", "cluster-map-empty")
            .style("display", "none")
            .text("No map coordinates available");

        const current = {
            container,
            clusters,
            svg,
            root,
            hullLayer,
            pointLayer,
            tooltip,
            resizeObserver: null,
            points: flattenClusters(clusters),
            selectedPaperIds: new Set(),
        };

        function draw() {
            const width = Math.max(container.clientWidth || 0, 320);
            const height = Math.max(container.clientHeight || 0, 280);
            const points = current.points.filter((point) => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)));

            svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);
            empty.style("display", points.length ? "none" : "flex");

            if (!points.length) {
                hullLayer.selectAll("*").remove();
                pointLayer.selectAll("*").remove();
                return;
            }

            const xExtent = d3.extent(points, (d) => Number(d.x));
            const yExtent = d3.extent(points, (d) => Number(d.y));
            const pad = 34;
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
                return {
                    cluster,
                    polygon: clusterPoints.length >= 3 ? d3.polygonHull(clusterPoints) : null,
                    points: clusterPoints,
                };
            });

            hullLayer.selectAll("path")
                .data(hulls.filter((item) => item.polygon), (d) => d.cluster.cluster_id)
                .join("path")
                .attr("class", "cluster-hull")
                .attr("d", (d) => `M${d.polygon.join("L")}Z`)
                .attr("fill", (d) => colorForCluster(d.cluster.cluster_id))
                .attr("stroke", (d) => colorForCluster(d.cluster.cluster_id))
                .on("click", (event, d) => {
                    event.stopPropagation();
                    container.dispatchEvent(new CustomEvent("cluster:select", {
                        bubbles: true,
                        detail: { cluster: d.cluster },
                    }));
                });

            hullLayer.selectAll("circle.cluster-centroid-target")
                .data(hulls, (d) => d.cluster.cluster_id)
                .join("circle")
                .attr("class", "cluster-centroid-target")
                .attr("cx", (d) => d.points.length ? d3.mean(d.points, (point) => point[0]) : 0)
                .attr("cy", (d) => d.points.length ? d3.mean(d.points, (point) => point[1]) : 0)
                .attr("r", (d) => Math.max(18, Math.min(42, 13 + d.points.length * 3)))
                .attr("fill", (d) => colorForCluster(d.cluster.cluster_id))
                .attr("stroke", (d) => colorForCluster(d.cluster.cluster_id))
                .on("click", (event, d) => {
                    event.stopPropagation();
                    container.dispatchEvent(new CustomEvent("cluster:select", {
                        bubbles: true,
                        detail: { cluster: d.cluster },
                    }));
                });

            pointLayer.selectAll("circle")
                .data(points, (d) => d.__paperId)
                .join("circle")
                .attr("class", "paper-dot")
                .attr("r", 5.2)
                .attr("cx", (d) => xScale(Number(d.x)))
                .attr("cy", (d) => yScale(Number(d.y)))
                .attr("fill", (d) => colorForCluster(d.__clusterId))
                .attr("data-paper-id", (d) => d.__paperId)
                .on("mouseenter", (event, d) => {
                    tooltip
                        .style("opacity", 1)
                        .html(`
                            <strong>${escapeHtml(d.title || "Untitled paper")}</strong>
                            <span>${escapeHtml([d.venue, d.year].filter(Boolean).join(" · ") || "Unknown venue")}</span>
                        `);
                    d3.select(event.currentTarget).classed("is-hovered", true);
                })
                .on("mousemove", (event) => {
                    tooltip
                        .style("left", `${event.pageX + 14}px`)
                        .style("top", `${event.pageY + 14}px`);
                })
                .on("mouseleave", (event) => {
                    tooltip.style("opacity", 0);
                    d3.select(event.currentTarget).classed("is-hovered", false);
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
            current.pointLayer.selectAll("circle")
                .classed("paper-dot--highlighted", (d) => selected.has(d.__paperId) || selected.has(paperId(d)))
                .classed("paper-dot--dimmed", (d) => selected.size > 0 && !selected.has(d.__paperId) && !selected.has(paperId(d)));
        }

        svg.call(
            d3.zoom()
                .scaleExtent([0.7, 7])
                .on("zoom", (event) => {
                    root.attr("transform", event.transform);
                })
        );

        svg.on("click", () => {
            container.dispatchEvent(new CustomEvent("map:clear", { bubbles: true }));
        });

        current.resizeObserver = new ResizeObserver(draw);
        current.resizeObserver.observe(container);
        state = current;
        draw();
        return current;
    }

    function highlightPapers(paperIds = []) {
        if (!state) return;
        state.selectedPaperIds = new Set((paperIds || []).map((id) => String(id)).filter(Boolean));
        state.pointLayer.selectAll("circle")
            .classed("paper-dot--highlighted", (d) => state.selectedPaperIds.has(d.__paperId) || state.selectedPaperIds.has(paperId(d)))
            .classed("paper-dot--dimmed", (d) => state.selectedPaperIds.size > 0 && !state.selectedPaperIds.has(d.__paperId) && !state.selectedPaperIds.has(paperId(d)));
    }

    function clearHighlight() {
        highlightPapers([]);
    }

    window.ClusterMap = {
        render,
        highlightPapers,
        clearHighlight,
        destroy,
        colors: TABLEAU_10,
        paperId,
    };
})();
