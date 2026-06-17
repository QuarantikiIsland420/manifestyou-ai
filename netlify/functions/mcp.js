const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-API-Key, Authorization, Mcp-Session-Id",
};

const TOOLS = [
  {
    name: "get_intention",
    description: "Fetch a ManifestYOU soul document — a short philosophical grounding text designed to be injected into an AI system prompt before a session begins. Call this at the start of a session to orient the model toward stillness, precision, or creative expansion before work. Paste the returned soul_document into your system prompt or before the first user message.",
    inputSchema: {
      type: "object",
      properties: {
        session_type: {
          type: "string",
          enum: ["general", "analytical", "creative", "customer_service"],
          description: "Session orientation. analytical=precision and decision support. creative=generative and brand work. customer_service=grounded and human-facing. general=default.",
          default: "general",
        },
      },
      required: [],
    },
  },
];

function jsonrpc(id, result) {
  return {
    statusCode: 200,
    headers: { ...CORS, "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id, result }),
  };
}

function jsonrpcError(id, code, message) {
  return {
    statusCode: 200,
    headers: { ...CORS, "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }),
  };
}

exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers: CORS, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return { statusCode: 405, headers: { ...CORS, "Content-Type": "application/json" }, body: JSON.stringify({ error: "Method not allowed" }) };
  }

  let msg;
  try {
    msg = JSON.parse(event.body || "{}");
  } catch {
    return jsonrpcError(null, -32700, "Parse error");
  }

  const { id, method, params = {} } = msg;

  // Notifications have no id — acknowledge silently
  if (id === undefined || id === null) {
    return { statusCode: 204, headers: CORS, body: "" };
  }

  if (method === "initialize") {
    return jsonrpc(id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "manifestyou", version: "1.0.0" },
    });
  }

  if (method === "ping") {
    return jsonrpc(id, {});
  }

  if (method === "tools/list") {
    return jsonrpc(id, { tools: TOOLS });
  }

  if (method === "tools/call") {
    const { name, arguments: args = {} } = params;

    if (name !== "get_intention") {
      return jsonrpcError(id, -32601, `Unknown tool: ${name}`);
    }

    const sessionType = args.session_type || "general";
    const apiKey = (
      (event.headers["authorization"] || "").replace(/^Bearer\s+/i, "") ||
      event.headers["x-api-key"] ||
      ""
    ).trim();

    if (!apiKey) {
      return jsonrpc(id, {
        content: [{ type: "text", text: JSON.stringify({ error: "Unauthorized. Provide a valid Authorization: Bearer <key> or X-API-Key header.", info: "https://manifestyou.ai/for-models" }) }],
        isError: true,
      });
    }

    try {
      const res = await fetch(
        `https://manifestyou.ai/.netlify/functions/invoke`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${apiKey}`,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ session_type: sessionType })
        }
      );
      const data = await res.json();

      return jsonrpc(id, {
        content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
      });
    } catch (err) {
      return jsonrpcError(id, -32000, `Failed to fetch invocation: ${err.message}`);
    }
  }

  return jsonrpcError(id, -32601, `Method not found: ${method}`);
};
