#!/data/data/com.termux/files/usr/bin/bash
# Astro build on Termux. NOT needed on CI or the VPS — those have native
# bindings for linux and run `npm ci && npm run build`.
#
# Three upstream packages ship no Android build, so each needs a workaround:
#   satteri  -> WASI build   (@bruits/satteri-android-arm64 is a 404 on npm)
#   sharp    -> WASI build   (@img/sharp-android-arm64 is a 404 on npm)
#   pagefind -> static musl binary (no android-arm64 npm package)
#
# `--force` is required: npm rejects `cpu: "wasm32"` on arm64. That also means
# the install fails loudly if the network is unavailable — rerun it after any
# `rm -rf node_modules`.
#
# The `node_modules/.bin/astro` shim is skipped on purpose: its `#!/usr/bin/env`
# shebang cannot resolve, because /usr/bin/env does not exist on Termux.
set -e
cd "$(dirname "$0")" || exit 1

WASMI=(
	'@bruits/satteri-wasm32-wasi'
	'@img/sharp-wasm32'
)
missing=0
for p in "${WASMI[@]}"; do
	[ -d "node_modules/$p" ] || missing=1
done
if [ "$missing" = 1 ]; then
	echo "installing Termux-only WASM fallbacks..." >&2
	npm install --no-save --force "${WASMI[@]}" >&2
fi

export NAPI_RS_FORCE_WASI=true
export PAGEFIND_BINARY_PATH=${PAGEFIND_BINARY_PATH:-$PWD/../pf/pagefind}
exec node ./node_modules/astro/bin/astro.mjs build "$@"