const BASE_URL = (() => {
    const configuredBase =
        window.__RA_API_BASE_URL__
        || document.querySelector('meta[name="ra-api-base"]')?.content?.trim();

    if (configuredBase) {
        return configuredBase.replace(/\/+$/, "");
    }

    const currentOrigin = window.location?.origin;
    
    if (currentOrigin && /^https?:/.test(currentOrigin)) {
        return currentOrigin;
    }

    return "";
})();

function getHeaders({ hasBody = false, includeAuth = true } = {}) {
    const token = localStorage.getItem("access_token");
    const headers = {};

    if (hasBody) {
        headers["Content-Type"] = "application/json";
    }

    if (includeAuth && token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    return headers;
}

// Routes outside the workspace where a 401 should NOT trigger a redirect
// (the user is already in the auth flow, or viewing a public surface).
const AUTH_REDIRECT_SAFE_PREFIXES = ["/html/login.html", "/html/signup.html", "/html/verify-otp.html", "/html/forgot-password.html", "/html/reset-password.html", "/html/oauth-callback.html", "/synthesis/share/"];

function shouldInterceptAuthRedirect() {
    const path = window.location?.pathname || "";
    return !AUTH_REDIRECT_SAFE_PREFIXES.some((prefix) => path.startsWith(prefix));
}

function handleUnauthorized() {
    if (!shouldInterceptAuthRedirect()) return;
    try {
        sessionStorage.setItem("auth:session-expired", "1");
    } catch (_e) { /* private mode — ignore */ }
    localStorage.removeItem("access_token");
    localStorage.removeItem("username");
    const next = window.location.pathname + window.location.search;
    const sameOrigin = next.startsWith("/") && !next.startsWith("//");
    const query = sameOrigin ? `?next=${encodeURIComponent(next)}` : "";
    window.location.replace(`/html/login.html${query}`);
}

async function authenticatedFetch(url, options = {}) {
    options.headers = {
        ...options.headers,
        ...getHeaders({ hasBody: !!options.body })
    };
    const response = await fetch(url, options);
    if (response.status === 401) {
        handleUnauthorized();
    }
    return response;
}

async function signup(username, email, password, role) {
    const response = await fetch(`${BASE_URL}/signup`, {
        method: "POST",
        headers: getHeaders({ hasBody: true, includeAuth: false }),
        body: JSON.stringify({ username, email, password, role })
    })
    return await response.json()
}

async function login(username, password) {
    const response = await fetch(`${BASE_URL}/login`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: `username=${username}&password=${password}`
    })
    const data = await response.json()
    if (data.access_token) {
        localStorage.setItem("access_token", data.access_token)
    }
    return data
}

function signOut() {
    localStorage.removeItem("access_token")
    localStorage.removeItem("username")
    window.location.href = window.location.protocol.startsWith("http") ? "/" : "index.html"
}

function isLoggedIn() {
    const token = localStorage.getItem("access_token")
    return !!(token && token !== "undefined" && token !== "null")
}

async function fetchPapers() {
    const response = await fetch(`${BASE_URL}/papers`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchPaper(paper_id) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function addPaper(paperData) {
    const response = await fetch(`${BASE_URL}/papers`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(paperData)
    })
    return await response.json()
}

async function updatePaper(paper_id, paperData) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "PUT",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(paperData)
    })
    return await response.json()
}

async function deletePaper(paper_id) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "DELETE",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchReports() {
    const response = await fetch(`${BASE_URL}/reports`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchReport(report_id) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function addReport(reportData) {
    const response = await fetch(`${BASE_URL}/reports`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(reportData)
    })
    return await response.json()
}

async function updateReport(report_id, reportData) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "PUT",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(reportData)
    })
    return await response.json()
}

async function deleteReport(report_id) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "DELETE",
        headers: getHeaders()
    })
    return await response.json()
}