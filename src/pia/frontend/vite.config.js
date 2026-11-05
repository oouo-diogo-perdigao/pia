import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  base: "/pia/",
  resolve: {
    dedupe: [
      "react",
      "react-dom",
      "@mantine/core",
      "@mantine/hooks",
      "lucide-react",
      "react-markdown",
      "remark-gfm",
    ],
  },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../assets",
    emptyOutDir: true,
    sourcemap: true,
    minify: "esbuild",
    lib: {
      entry: fileURLToPath(new URL("./main.jsx", import.meta.url)),
      formats: ["es"],
      fileName: () => "workspace.js",
      cssFileName: "workspace",
    },
    rollupOptions: {
      external: ["/pia/media.js"],
      onwarn(warning, handler) {
        if (warning.code !== "MODULE_LEVEL_DIRECTIVE") handler(warning);
      },
      output: { assetFileNames: "[name][extname]" },
    },
  },
  esbuild: { jsx: "automatic" },
});
