# AgentOps Control Plane — Frontend

React and TypeScript dashboard for the AgentOps Control Plane.

## Current capabilities

- Live Agent Registry backed by FastAPI and PostgreSQL
- Agent registration and listing
- Agent status and configuration display
- API connection status and manual refresh
- Responsive dashboard layout

## Planned capabilities

- Agent runs and execution traces
- Tool Gateway and policy decisions
- Human-in-the-loop approvals
- Evaluations and benchmarks
- Reliability Replay & Policy Proof

These planned capabilities are not yet implemented.

## Technology

- React and TypeScript
- Vite
- Lucide React
- Oxlint

## Local development

Prerequisites: Node.js, npm, and the AgentOps FastAPI backend.

From the repository root:

    npm install --prefix frontend
    npm run dev --prefix frontend

Open http://localhost:5173/

The Vite development server proxies /api requests to the
FastAPI backend at http://127.0.0.1:8000.

The backend must be running to display live agent data.

## Quality checks

From the repository root:

    npm run lint --prefix frontend
    npm run build --prefix frontend

## Project structure

- src/App.tsx — Dashboard and Agent Registry interface
- src/App.css — Dashboard component styling
- src/index.css — Global styling
- src/api.ts — Typed API client
- vite.config.ts — Vite configuration and API proxy

## Project status

Under active development as part of a 15-day AI engineering
portfolio project. Reliability and security capabilities
will be added incrementally and verified through tests.
