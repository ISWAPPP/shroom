UI component regression checks

Run from the repository: tests/ui/run.sh

Prerequisites: Node.js and frontend dependencies (npm ci in frontend).
The runner installs pinned jsdom in the scratch cache, bundles the current
ChatList component, and renders it with React in a simulated DOM.
It never logs into the portal or deletes real chats.

Covered: safe initial focus, Tab/Shift+Tab wrapping, focus restoration,
delete progress, disabled controls, blocked dismissal while pending,
and recovery after a rejected request.

These checks complement tests/run_all.sh; they are not Chrome visual tests.
