import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted fonts: the app must work without internet access.
import "@fontsource/bricolage-grotesque/600.css";
import "@fontsource/bricolage-grotesque/700.css";
import "@fontsource/bricolage-grotesque/800.css";
import "@fontsource/figtree/400.css";
import "@fontsource/figtree/500.css";
import "@fontsource/figtree/600.css";
import "@fontsource/figtree/700.css";
import "./styles/globals.css";

import { App } from "./app/App";
import { APP_NAME } from "./lib/api";

document.title = APP_NAME;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
