// Runs after `npm install`: copies the MediaPipe wasm runtime into public/ so face detection works without internet.
import { cpSync, mkdirSync } from "node:fs"

mkdirSync("public/mediapipe", { recursive: true })
cpSync("node_modules/@mediapipe/tasks-vision/wasm", "public/mediapipe/wasm", { recursive: true })
