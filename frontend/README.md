# Frontend

React 18 + TypeScript + Vite + Tailwind CSS 4. Talks to the FastAPI backend through the `/api` proxy (Vite in development, nginx in Docker).

```bash
npm install
npm run dev        # http://localhost:3000  (needs the backend on :8000)
npm run build      # type-check and production build
```

- `src/App.tsx`: entry points. `/a/<slug>` selects the organisation; login and sign-up are bound to it.
- `src/context/AuthContext.tsx`, `src/api.ts`: session handling (Bearer token, server-side logout, expiry handling).
- `src/pages/ChatPage.tsx`: conversations, SSE streaming with Stop, confirmation cards.
- `src/components/RichCards.tsx`: order summary, booking summary, slot picker, status cards.
- `e2e/ui_check.py`: browser checks at 375px and 1280px (see the header of that file).
