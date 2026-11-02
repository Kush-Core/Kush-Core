"""Profile content shared by the generators: one place to edit text.

Project descriptions come from each repository's README (confirmed in the repo
audit). The Proclamation lines are the profile's About bullets.
"""

PROCLAMATION = [  # paragraphs; each is a list of display lines
    ["B.Tech CSE, MIT Bengaluru ('27) · seeking software engineering internships"],
    ["I build async Python services (FastAPI), graph-backed data (Neo4j) and LLM extraction pipelines"],
    ["A devotee of the medieval — scriptoria, heraldry, candlelight —",
     "writing today's code with the same patience"],
]

PROJECTS = {
    "Narrative_mind": {
        "name": "Narrative Mind",
        "epithet": "The Web of Tales",
        "line": "Fictional worlds as a Neo4j graph, with LLM extraction and Graph RAG",
        "chips": ["FastAPI", "Neo4j", "Ollama / Groq", "React + TypeScript"],
        "chip_label": None,
        "status": None,
    },
    "hubahu": {
        "name": "Hubahu",
        "epithet": "The Listening Scribe",
        "line": "Checks Hindi audio episodes against their scripts and flags mismatches",
        "chips": ["FastAPI", "Postgres", "ONNX Runtime"],
        "chip_label": "In progress · planned stack",
        "status": "in progress",
    },
    "Renewal-risk": {
        "name": "Renewal Risk",
        "epithet": "The Ledger of Fortunes",
        "line": "Churn risk per renewal decision from a 23M-row subscription payment log",
        "chips": ["Python", "DuckDB", "scikit-learn", "lifelines"],
        "chip_label": None,
        "status": None,
    },
    "Throttling1": {
        "name": "Throttling1",
        "epithet": "The Clockwork Trial",
        "line": "How compiler flags, scheduler contention and threads change a 100M-float sum",
        "chips": ["C++", "clang", "Apple M1"],
        "chip_label": None,
        "status": None,
    },
}
