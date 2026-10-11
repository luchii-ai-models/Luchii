#!/usr/bin/env node
/*
 * Compiles the Frasberg TypeScript engines (packages/*-engine) into a JSON IR that the Python
 * Engine Runtime (backend/engine_runtime) interprets. Run from /app:
 *     node scripts/build_engine_ir.js
 * Type annotations are stripped, then each file is parsed with acorn; every exported function is kept as ESTree.
 */
const fs = require("fs");
const path = require("path");
const acorn = require(path.join(__dirname, "../frontend/node_modules/acorn"));

const ROOT = path.join(__dirname, "..");
const PKG = path.join(ROOT, "packages");
const OUT = path.join(ROOT, "backend/engine_runtime/engines_ir.json");

function stripTypes(src) {
  return src
    .replace(/^\s*import[^;]*;\s*$/gm, "")
    .replace(/^\s*export\s*\{[^}]*\}\s*from[^;]*;\s*$/gm, "")
    .replace(/export\s+(interface|type)\s+\w+[^{=]*(\{[\s\S]*?\n\}|=[^;]*;)/g, "")
    .replace(/function\s+(\w+)\s*\(([^)]*)\)\s*(:\s*[^{]+)?\{/g, (_, n, params) =>
      `function ${n}(${params.split(",").map((p) => p.split(":")[0].replace("?", "").trim()).filter(Boolean).join(", ")}) {`)
    .replace(/\b(const|let|var)\s+(\w+)\s*:\s*[^=;]+=/g, "$1 $2 =")
    .replace(/\s+as\s+[A-Za-z_][\w.<>\[\]]*/g, "");
}

function interfaceFields(src) {
  const m = src.match(/interface\s+(\w+)[^{]*\{([\s\S]*?)\n\}/);
  if (!m) return null;
  const fields = [...m[2].matchAll(/^\s*(\w+)(\?)?\s*:\s*([^;]+);/gm)].map((x) => ({ name: x[1], optional: !!x[2], type: x[3].trim() }));
  return { name: m[1], fields };
}

function strip(node) {
  if (Array.isArray(node)) return node.map(strip);
  if (!node || typeof node !== "object") return node;
  const out = {};
  for (const [k, v] of Object.entries(node)) {
    if (k === "start" || k === "end" || k === "loc" || k === "range" || k === "raw") continue;
    out[k] = strip(v);
  }
  return out;
}

const engines = {};
const problems = [];
for (const dir of fs.readdirSync(PKG).sort()) {
  if (!dir.endsWith("-engine")) continue;
  const full = path.join(PKG, dir);
  if (!fs.existsSync(path.join(full, "evolve.ts"))) continue; // only the standard builder/graph/envelope/evolve engines
  const id = dir.replace(/-engine$/, "");
  const eng = { id, package: `packages/${dir}`, files: {}, model: null };
  for (const file of fs.readdirSync(full).sort()) {
    if (!file.endsWith(".ts") || file === "index.ts") continue;
    const src = fs.readFileSync(path.join(full, file), "utf8");
    if (/interface\s+\w+/.test(src) && !/function\s/.test(src)) {
      eng.model = interfaceFields(src);
      continue;
    }
    let ast;
    try {
      ast = acorn.parse(stripTypes(src), { ecmaVersion: "latest", sourceType: "module" });
    } catch (e) {
      problems.push(`${dir}/${file}: ${e.message}`);
      continue;
    }
    const fns = [];
    for (const st of ast.body) {
      const decl = st.type === "ExportNamedDeclaration" ? st.declaration : st;
      if (decl && decl.type === "FunctionDeclaration") {
        fns.push({ name: decl.id.name, params: decl.params.map((p) => p.name), body: strip(decl.body) });
      }
    }
    if (fns.length) eng.files[file.replace(/\.ts$/, "")] = fns;
  }
  engines[id] = eng;
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ generated_from: "packages/*-engine (TypeScript)", engines }, null, 0));
console.log(`engines: ${Object.keys(engines).length}, functions: ${Object.values(engines).reduce((n, e) => n + Object.values(e.files).flat().length, 0)}`);
if (problems.length) { console.log("PARSE PROBLEMS:\n" + problems.join("\n")); process.exitCode = 1; }
