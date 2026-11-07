// K-belge-ciktilari: the document viewer's script (src/views/office/viewer.ts), with docx-preview, SheetJS and
// pptx-preview inside it, as one classic script beside public/office/viewer.html - a frame of no origin loads no module
// script without CORS. Built after the app's own build, into its dist.
import { defineConfig } from 'vite'

export default defineConfig({
  publicDir: false,
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: 'dist/office',
    emptyOutDir: false,
    lib: { entry: 'src/views/office/viewer.ts', formats: ['iife'], name: 'koloniOffice', fileName: () => 'viewer.js' },
  },
})
