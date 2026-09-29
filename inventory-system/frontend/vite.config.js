import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false,
      },
      // 👇 ADD THESE TWO ROUTES to handle the image capturing mechanism
      "/capture": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false,
      },
      "/video_feed": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
