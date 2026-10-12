# Local draw.io editor

`drawio/` is a sparse checkout of `jgraph/drawio` version 31.5.3 at commit
`0f419a92c769adb5fb20f2b18053a5ae8c7e4993` (Apache-2.0; see
`drawio/LICENSE`). MindPilot serves its web editor at `/drawio/` in development
and copies the web app plus license into the production build.

MindPilot's changes live in the upstream source files:

- `src/main/webapp/js/diagramly/EditorUi.js`: canvas-only mode for `mindpilot=1`.
- `src/main/webapp/js/grapheditor/EditorUi.js`: keep canvas scrollbars disabled.
- `src/main/webapp/styles/grapheditor.css`: one-column canvas layout; no side panels.

The app loads the unminified source with `dev=1`, so these edits are active in
both development and production without modifying the upstream minified bundle.
