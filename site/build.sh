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

# satteri's WASI shim preopens the filesystem root as its sandbox root. Termux's
# sandbox refuses that (UVWASI_EACCES), so point it at the project instead. Any
# `npm install` restores the pristine file, so this is re-applied every build
# rather than checked for existence — a stale check here silently breaks the
# build with a confusing WASI error rather than a missing-module one.
WASI_SHIM=node_modules/@bruits/satteri-wasm32-wasi/satteri_napi.wasi.cjs
if [ -f "$WASI_SHIM" ]; then
	python3 - "$WASI_SHIM" <<'PY' >&2
import re, sys
p = sys.argv[1]
s = open(p, encoding='utf8').read()
patched = 'process.env.SATTERI_WASI_PREOPEN'
if patched in s:
    sys.exit(0)
# Only ever replace the real declaration, never a comment mentioning it.
new, n = re.subn(
    r"const __rootDir = __nodePath\.parse\(process\.cwd\(\)\)\.root",
    "const __rootDir = process.env.SATTERI_WASI_PREOPEN || process.cwd()",
    s,
)
if n != 1:
    sys.exit(f"build.sh: expected one __rootDir declaration in {p}, found {n}")
open(p, 'w', encoding='utf8').write(new)
print(f"build.sh: patched WASI preopen in {p}")
PY
fi

export NAPI_RS_FORCE_WASI=true
export PAGEFIND_BINARY_PATH=${PAGEFIND_BINARY_PATH:-$PWD/../pf/pagefind}
exec node ./node_modules/astro/bin/astro.mjs build "$@"
