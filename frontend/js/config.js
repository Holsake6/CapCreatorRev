// Where the backend API lives. The run scripts start it on port 8765 of the
// same machine; change apiBase here if you run the backend elsewhere.
window.APP_CONFIG = {
  apiBase: `${location.protocol}//${location.hostname || "127.0.0.1"}:8765`,
};
