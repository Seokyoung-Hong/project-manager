"use strict";

const readline = require("node:readline");

const API = "https://project.sio2.kr/mcp/relay/tools";
const token = process.env.SANDOL_PM_TOKEN;
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

function send(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

async function request(path = "", argumentsObject) {
  if (!token) throw new Error("ProjectManager API token is not configured in this extension.");
  const response = await fetch(API + path, {
    method: argumentsObject === undefined ? "GET" : "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(argumentsObject === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: argumentsObject === undefined ? undefined : JSON.stringify(argumentsObject),
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `ProjectManager HTTP ${response.status}`);
  return data;
}

async function dispatch(message) {
  const { id, method, params = {} } = message;
  if (id === undefined || id === null) return;
  try {
    let result;
    if (method === "initialize") {
      result = {
        protocolVersion: params.protocolVersion || "2025-06-18",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "sandol-project-manager-local", version: "1.0.0" },
        instructions: "Call get_guide first. Before writing, read the organization's governance and settings.",
      };
    } else if (method === "ping") {
      result = {};
    } else if (method === "tools/list") {
      result = await request();
    } else if (method === "tools/call") {
      if (typeof params.name !== "string" || !/^[A-Za-z0-9_]+$/.test(params.name)) {
        throw new Error("Invalid tool name.");
      }
      const data = await request(`/${params.name}`, params.arguments || {});
      result = {
        content: [{ type: "text", text: JSON.stringify(data.result) }],
        ...(data.result && typeof data.result === "object" && !Array.isArray(data.result)
          ? { structuredContent: data.result }
          : {}),
      };
    } else {
      send({ jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
      return;
    }
    send({ jsonrpc: "2.0", id, result });
  } catch (error) {
    if (method === "tools/call") {
      send({
        jsonrpc: "2.0", id,
        result: { content: [{ type: "text", text: String(error.message) }], isError: true },
      });
    } else {
      send({ jsonrpc: "2.0", id, error: { code: -32603, message: String(error.message) } });
    }
  }
}

rl.on("line", (line) => {
  try {
    const message = JSON.parse(line);
    void dispatch(message);
  } catch {
    process.stderr.write("Invalid MCP JSON message.\n");
  }
});
