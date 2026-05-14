async function parseResponse(response, fallbackMessage) {
    const data = await response.json();

    if (!response.ok) {
        const detail = Array.isArray(data.detail)
            ? data.detail.map((item) => item.msg || item.message).join(", ")
            : data.detail || data.message || fallbackMessage;
        throw new Error(detail);
    }

    return data;
}

async function searchPapers(payload) {
    const response = await fetch(`${BASE_URL}/search/papers`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Search failed");
}

async function analyzeGaps(payload) {
    const response = await fetch(`${BASE_URL}/synthesis/gaps`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Synthesis failed");
}

async function analyzeGapsStream(payload, onEvent) {
    const response = await fetch(`${BASE_URL}/synthesis/gaps/stream`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
        return await parseResponse(response, "Synthesis failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResult = null;

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "error") {
                throw new Error(event.detail || "Synthesis failed");
            }
            if (event.type === "result") {
                finalResult = event.data;
            }
            if (typeof onEvent === "function") {
                onEvent(event);
            }
        }
    }

    if (buffer.trim()) {
        const event = JSON.parse(buffer);
        if (event.type === "error") {
            throw new Error(event.detail || "Synthesis failed");
        }
        if (event.type === "result") {
            finalResult = event.data;
        }
        if (typeof onEvent === "function") {
            onEvent(event);
        }
    }

    if (!finalResult) {
        throw new Error("Synthesis finished without a result");
    }
    return finalResult;
}

async function exploreArxiv(payload) {
    const response = await fetch(`${BASE_URL}/explore/arxiv`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Explore failed");
}

async function fetchPublicReport(report_id) {
    const response = await fetch(`${BASE_URL}/synthesis/public/report/${report_id}`, {
        method: "GET",
        headers: getHeaders({ includeAuth: false }),
    });

    return await parseResponse(response, "Failed to load shared report");
}

function buildSearchPayload({ topic, year, venue, strictVenue, maxResults }) {
    const payload = {
        topic: topic.trim(),
        max_results: maxResults,
    };

    const normalizedYear = typeof year === 'string' ? year.trim() : '';
    if (normalizedYear) {
        payload.year = normalizedYear.replace(/\s*-\s*/g, '-');
    }

    if (venue && venue.trim()) {
        payload.venue = venue.trim();
        payload.strict_venue = strictVenue === true;
    }

    return payload;
}

function buildExplorePayload({ topic, year, venue, strictVenue, cursor = 0, pageSize = 20 }) {
    const trimmedTopic = (topic || '').trim();
    const payload = {
        cursor: Math.max(0, Number.parseInt(cursor, 10) || 0),
        page_size: Math.min(50, Math.max(1, Number.parseInt(pageSize, 10) || 20)),
    };
    if (trimmedTopic) {
        payload.topic = trimmedTopic;
    }

    const normalizedYear = typeof year === 'string' ? year.trim() : '';
    if (normalizedYear) {
        payload.year = normalizedYear.replace(/\s*-\s*/g, '-');
    }

    if (venue && venue.trim()) {
        payload.venue = venue.trim();
        payload.strict_venue = strictVenue === true;
    }

    return payload;
}

function formatFilters(filters) {
    const chips = [];

    if (filters.year) {
        const label = String(filters.year).includes('-') ? 'Year range' : 'Year';
        chips.push(`${label}: ${filters.year}`);
    }

    if (filters.venue) {
        const label = filters.strict_venue ? 'Venue (strict)' : 'Venue';
        chips.push(`${label}: ${filters.venue}`);
    }

    return chips;
}

function sourceLabel(source) {
    return source
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

async function fetchSearchHistory() {
    const response = await fetch(`${BASE_URL}/search/history`, {
        method: "GET",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to fetch search history");
}

async function deleteSearchHistory(history_id) {
    const response = await fetch(`${BASE_URL}/search/history/${history_id}`, {
        method: "DELETE",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to delete history");
}

async function clearSearchHistory() {
    const response = await fetch(`${BASE_URL}/search/history`, {
        method: "DELETE",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to clear search history");
}

async function fetchReport(report_id) {
    const response = await fetch(`${BASE_URL}/synthesis/report/${report_id}`, {
        method: "GET",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to fetch report");
}

window.searchAPI = {
    searchPapers,
    analyzeGaps,
    analyzeGapsStream,
    exploreArxiv,
    fetchReport,
    fetchPublicReport,
    buildSearchPayload,
    buildExplorePayload,
    formatFilters,
    sourceLabel,
    fetchSearchHistory,
    deleteSearchHistory,
    clearSearchHistory,
};

async function fetchChatHistory() {
    const response = await fetch(`${BASE_URL}/chat/history`, {
        method: "GET",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to fetch chat history");
}

async function saveChatMessage(payload) {
    const response = await fetch(`${BASE_URL}/chat/save`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(payload),
    });
    return await parseResponse(response, "Failed to save chat");
}

async function deleteChatSession(session_id) {
    const response = await fetch(`${BASE_URL}/chat/session/${session_id}`, {
        method: "DELETE",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to delete chat session");
}

async function clearChatHistory() {
    const response = await fetch(`${BASE_URL}/chat/clear`, {
        method: "DELETE",
        headers: getHeaders(),
    });
    return await parseResponse(response, "Failed to clear chat history");
}

window.chatAPI = {
    fetchChatHistory,
    saveChatMessage,
    deleteChatSession,
    clearChatHistory,
};
