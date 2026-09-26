import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Demo build: every import of src/api.js is swapped for the in-browser mock backend.
const MOCK = path.resolve(__dirname, "src/mock/mockBackend.js");
const REAL = path.resolve(__dirname, "src/api.js");
const useMockApi = {
  name: "use-mock-api",
  enforce: "pre",
  async resolveId(source, importer, options) {
    if (!source.endsWith("api.js") || !importer) return null;
    const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
    return resolved && resolved.id === REAL ? MOCK : null;
  },
};

export default defineConfig({
  plugins: [useMockApi, react()],
  build: { outDir: "dist-demo", assetsInlineLimit: 100000000, cssCodeSplit: false },
});
