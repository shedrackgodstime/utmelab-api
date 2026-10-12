#!/data/data/com.termux/files/usr/bin/bash
# Serve the built site. No WASI env vars needed -- preview only reads dist/.
# Must invoke the CLI directly: node_modules/.bin/astro has a `#!/usr/bin/env`
# shebang and /usr/bin/env does not exist on Termux.
cd "$(dirname "$0")" || exit 1
exec node ./node_modules/astro/bin/astro.mjs preview "$@"
