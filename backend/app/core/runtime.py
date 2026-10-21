"""Runtime detection without importing Cloudflare modules on normal servers."""
import sys

IS_WORKERS = sys.platform == "emscripten"
