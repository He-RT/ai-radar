import assert from "node:assert/strict";
import test from "node:test";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  WEB_ROUTE_CONTRACTS,
  validateActionRecipeProjection,
  validateBriefingProjection,
  validateRadarEventProjection,
  validateStoryProjection,
} from "../../packages/contracts/src/index.js";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const webRoot = path.join(repositoryRoot, "apps/web");
const requireFromWeb = createRequire(pathToFileURL(path.join(webRoot, "package.json")));
const ts = requireFromWeb("typescript");

async function pageRoutes(directory = path.join(webRoot, "app")) {
  const routes = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) routes.push(...(await pageRoutes(absolute)));
    if (entry.isFile() && entry.name === "page.tsx") {
      const relative = path.relative(path.join(webRoot, "app"), directory).split(path.sep).join("/");
      routes.push(relative ? `/${relative}` : "/");
    }
  }
  return routes;
}

async function loadRadarData() {
  const source = await readFile(path.join(webRoot, "data/radar.ts"), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString("base64")}`);
}

function assertValidCollection(name, values, validator) {
  assert.ok(Array.isArray(values), `${name} must be an array`);
  values.forEach((value, index) => {
    const result = validator(value);
    assert.equal(result.ok, true, `${name}[${index}]: ${JSON.stringify(result.errors)}`);
  });
}

test("the versioned web route inventory matches every Next.js page", async () => {
  const actual = (await pageRoutes()).sort();
  const expected = WEB_ROUTE_CONTRACTS.map(({ path: route }) => route).sort();
  assert.deepEqual(actual, expected);
});

test("each route declares the radar adapter exports it consumes", async () => {
  for (const route of WEB_ROUTE_CONTRACTS) {
    const sources = await Promise.all(route.sourceFiles.map(async (file) => ({
      file,
      source: await readFile(path.join(repositoryRoot, file), "utf8"),
    })));
    const combined = sources.map(({ source }) => source).join("\n");
    assert.match(combined, /export default/, `${route.path} must have a default route component`);
    for (const dataExport of route.dataExports) {
      let consumed = false;
      for (const { file, source } of sources) {
        const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
        const imports = [];
        const identifierCounts = new Map();
        function visit(node) {
          if (ts.isIdentifier(node)) {
            identifierCounts.set(node.text, (identifierCounts.get(node.text) ?? 0) + 1);
          }
          if (
            ts.isImportDeclaration(node) &&
            ts.isStringLiteral(node.moduleSpecifier) &&
            node.moduleSpecifier.text.includes("data/server") &&
            node.importClause?.namedBindings &&
            ts.isNamedImports(node.importClause.namedBindings)
          ) {
            for (const element of node.importClause.namedBindings.elements) {
              imports.push({
                imported: (element.propertyName ?? element.name).text,
                local: element.name.text,
              });
            }
          }
          ts.forEachChild(node, visit);
        }
        visit(ast);
        consumed ||= imports.some(
          ({ imported, local }) => imported === dataExport && (identifierCounts.get(local) ?? 0) > 1,
        );
      }
      assert.equal(consumed, true, `${route.path} must import and use its declared ${dataExport} contract`);
    }
  }
});

test("the local web adapter satisfies every route projection contract", async () => {
  const data = await loadRadarData();
  assertValidCollection("radarEvents", data.radarEvents, validateRadarEventProjection);
  assertValidCollection("actions", data.actions, validateActionRecipeProjection);
  assertValidCollection("stories", data.stories, validateStoryProjection);
  assertValidCollection("briefings", data.briefings, validateBriefingProjection);

  const eventSlugs = new Set(data.radarEvents.map(({ slug }) => slug));
  const actionSlugs = new Set(data.actions.map(({ slug }) => slug));
  for (const event of data.radarEvents) {
    assert.ok(actionSlugs.has(event.actionSlug), `${event.slug} references a missing action`);
  }
  for (const action of data.actions) {
    assert.ok(eventSlugs.has(action.relatedEvent), `${action.slug} references a missing event`);
  }
  for (const story of data.stories) {
    for (const eventSlug of story.events) {
      assert.ok(eventSlugs.has(eventSlug), `${story.slug} references a missing event`);
    }
  }
});

test("the for-you route selects shared facts without mutating the server dataset", async () => {
  const data = await loadRadarData();
  const source = await readFile(path.join(webRoot, "app/for-you/page.tsx"), "utf8");
  const ast = ts.createSourceFile("for-you.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const mutations = [];
  const aliases = new Set(["dataset.events"]);
  let sliceCalls = 0;

  function rootedAtRadarEvents(node) {
    if (ts.isIdentifier(node)) return aliases.has(node.text);
    if (
      ts.isPropertyAccessExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "dataset" &&
      node.name.text === "events"
    ) return aliases.has("dataset.events");
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      return rootedAtRadarEvents(node.expression);
    }
    return false;
  }

  let addedAlias = true;
  while (addedAlias) {
    addedAlias = false;
    function discoverAliases(node) {
      if (
        ts.isVariableDeclaration(node) &&
        ts.isIdentifier(node.name) &&
        node.initializer &&
        rootedAtRadarEvents(node.initializer) &&
        !aliases.has(node.name.text)
      ) {
        aliases.add(node.name.text);
        addedAlias = true;
      }
      ts.forEachChild(node, discoverAliases);
    }
    discoverAliases(ast);
  }

  function visit(node) {
    if (
      ts.isBinaryExpression(node) &&
      ts.isAssignmentOperator(node.operatorToken.kind) &&
      rootedAtRadarEvents(node.left)
    ) {
      mutations.push(node.getText(ast));
    }
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) && rootedAtRadarEvents(node.operand)) {
      mutations.push(node.getText(ast));
    }
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      rootedAtRadarEvents(node.expression.expression)
    ) {
      const method = node.expression.name.text;
      if (["copyWithin", "fill", "pop", "push", "reverse", "shift", "sort", "splice", "unshift"].includes(method)) {
        mutations.push(node.getText(ast));
      }
      if (method === "slice") sliceCalls += 1;
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);

  assert.deepEqual(mutations, []);
  assert.ok(sliceCalls > 0, "for-you must select from the shared public event array");
  assert.ok(data.radarEvents.length >= 3, "fixture must exercise a meaningful personalized selection");
});
