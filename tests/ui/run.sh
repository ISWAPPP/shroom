#!/usr/bin/env bash
# Isolated UI tests; does not touch portal data or production dependencies.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CACHE="${TMPDIR:-/tmp}/shroom-ui-tests"
mkdir -p "$CACHE"
if [ ! -d "$CACHE/node_modules/jsdom" ]; then
  npm install --prefix "$CACHE" jsdom@27.4.0 --no-audit --no-fund
fi
export CHAT_LIST_BUNDLE="$CACHE/chat-list.cjs"
export NODE_PATH="$ROOT/frontend/node_modules:$CACHE/node_modules"
cd "$ROOT/frontend"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/ChatList.tsx'],outfile:process.env.CHAT_LIST_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react'],loader:{'.woff2':'empty'}});"
node "$ROOT/tests/ui/delete-dialog.cjs"
node "$ROOT/tests/ui/chat-menu.cjs"
export MARKDOWN_BUNDLE="$CACHE/markdown.cjs"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/MarkdownImpl.tsx'],outfile:process.env.MARKDOWN_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react']});"
node "$ROOT/tests/ui/copy-code.cjs"
node "$ROOT/tests/ui/rename.cjs"
export SETTINGS_BUNDLE="$CACHE/settings.cjs"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/Settings.tsx'],outfile:process.env.SETTINGS_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react','react-dom'],loader:{'.woff2':'empty'}});"
node "$ROOT/tests/ui/settings-history.cjs"
export ACTIVITY_BUNDLE="$CACHE/activity.cjs"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/AgentActivity.tsx'],outfile:process.env.ACTIVITY_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react']});"
node "$ROOT/tests/ui/activity.cjs"
node "$ROOT/tests/ui/activity-disclosure.cjs"
export EDITOR_BUNDLE="$CACHE/profile-editor.cjs"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/ProfileAgentEditor.tsx'],outfile:process.env.EDITOR_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react','react-dom'],loader:{'.woff2':'empty'}});"
node "$ROOT/tests/ui/profile-editor.cjs"
export THEME_BUNDLE="$CACHE/theme.cjs"
node --input-type=module -e "import {build} from 'esbuild'; await build({entryPoints:['src/Theme.tsx'],outfile:process.env.THEME_BUNDLE,bundle:true,platform:'node',format:'cjs',external:['react','react-dom'],loader:{'.woff2':'empty'}});"
node "$ROOT/tests/ui/themes.cjs"
