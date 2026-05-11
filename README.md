# Research Agent: Enterprise-Grade Research Intelligence

Research Agent is a premium, high-fidelity command center designed for modern researchers. It leverages advanced AI to accelerate literature reviews, identify critical research gaps, and visualize the topography of scientific knowledge.

## ✨ Key Features

### 🔍 Hero Omnibar Search
An integrated, glass-morphic search experience. Filter your research by year range, specific venues (ICML, ArXiv, etc.), and result volume to get exactly what you need.

### 🚀 Agent Orchestration UI
A state-of-the-art loading experience. Watch as the System Agent orchestrates the retrieval and synthesis pipeline in real-time, featuring:
- **Ambient Glow Physics**: A breathing background illumination that signals active processing.
- **Typographic Shimmers**: Smooth, shimmering status updates.
- **Execution Log**: A transparent, step-by-step log of the agent's progress (Retrieval -> Synthesis -> Topology Mapping).

### 🗺️ Interactive Literature Map
A high-performance D3.js visualization that maps the research landscape. 
- Discover thematic clusters.
- Explore topographical hulls representing knowledge domains.
- Seamlessly transition between global overviews and specific paper details.

### 🗂️ Workspace Dashboard
A streamlined command center for your research projects:
- **Project Cards**: High-fidelity cards with hover-lift physics for seamless resumption of past tasks.
- **Typing Indicators**: Calming, "breathing" UI interactions that reduce cognitive load during processing.
- **Technical Console**: A collapsible panel for environment monitoring and API status.

### 🛡️ Production Security & Performance
Hardened infrastructure for real-world deployment:
- **JWT Authentication**: Secure, token-based sessions for all users.
- **Role-Based Access Control (RBAC)**: Fine-grained permissions (Admin, Researcher, Viewer).
- **Personal API Keys**: Generate and manage keys for programmatic research access.
- **Rate Limiting**: Intelligent protection against API abuse (60 req/min).
- **Cursor-based Pagination**: High-performance history retrieval for large datasets.
- **Optimized Persistence**: MongoDB connection pooling and targeted indexing.

## 🛠️ Tech Stack

### Backend
- **FastAPI**: High-performance Python web framework.
- **Uvicorn**: Lightning-fast ASGI server implementation.
- **AI Engines**: Custom retrieval and synthesis services for paper analysis.

### Frontend
- **Alpine.js**: Lightweight reactive state management.
- **D3.js**: Professional-grade data visualizations for the Literature Map.
- **Vanilla CSS**: A custom, premium design system focused on glassmorphism, depth, and micro-animations.

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js (for dependency management)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd research-agent
   ```

2. **Set up the Python environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Install Frontend Dependencies**:
   ```bash
   npm install
   ```

4. **Run the Application**:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

Visit `http://localhost:8000/workspace` to start your first research project.

### 💻 VS Code Setup
The project includes a `.vscode` configuration for an optimal development experience:
- **Auto-formatting**: Enabled on save using standard Python tools.
- **Debugger**: Pre-configured "FastAPI: Research Agent" launch target.
- **Interpreter**: Automatically points to the `.venv` directory.

## 📁 Project Structure

```text
research-agent/
├── app/                # FastAPI Backend
│   ├── api/            # API endpoints
│   ├── core/           # Core logic & configuration
│   ├── services/       # AI & Search services
│   └── main.py         # Application entry point
├── frontend/           # Frontend Assets
│   ├── css/            # Premium Design System (dashboard.css, workspace.css)
│   ├── html/           # Page templates (index.html)
│   └── js/             # Application logic (Alpine.js, D3.js)
├── requirements.txt    # Python dependencies
└── pyproject.toml      # Project metadata
```

---
*Built with precision and passion for the research community.*
