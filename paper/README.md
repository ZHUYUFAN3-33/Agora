# Paper figure (annotated dummy dialogue)

Standalone Vite app for thesis/paper screenshots: **Scene layer**, **Response Examples** with dummy multi-agent dialogue, and **Decision / EXPRESSION** side panels.

- Press **`x`** to toggle highlighted spans (purple = Decision layer, salmon = EXPRESSION). Only text with clear linguistic realizations is annotated (see footnote on page).

## Run

```bash
cd paper
npm install
npm run dev
```

Opens at **http://localhost:5173** (or next free port). Use another port if it conflicts with the main frontend: `npm run dev -- --port 5174`.

## Build

```bash
npm run build
```

Output in `paper/dist/` (ignored by git).
