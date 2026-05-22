import time
from fastapi import FastAPI, Request, status 
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

# OpenTelemetry core imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# 1. Setup OpenTelemetry with an In-Memory Exporter
provider = TracerProvider()
memory_exporter = InMemorySpanExporter()
provider.add_span_processor(SimpleSpanProcessor(memory_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("my-internal-agent-tracer")

app = FastAPI(title="Self-Hosted Agent Observability")

# Simple memory storage for our chat room text
chat_history = []

# --- MOCK AI AGENT LOGIC ---
def call_llm(prompt: str):
    with tracer.start_as_current_span("llm_inference") as span:
        span.set_attribute("gen_ai.request.model", "llama-3-local")
        span.set_attribute("gen_ai.prompt", prompt)
        time.sleep(0.4)  # Simulate LLM compute delay
        response = f"Agent Response to: '{prompt}'"
        span.set_attribute("gen_ai.response", response)
        return response

def check_database(query: str):
    with tracer.start_as_current_span("agent_tool_db_lookup") as span:
        span.set_attribute("db.system", "sqlite")
        span.set_attribute("db.query", f"SELECT * FROM context WHERE key LIKE '%{query}%'")
        time.sleep(0.15)  # Simulate DB latency
        return "Database found matching context token."


# --- ROUTES ---

# 1. The Chat Endpoint
@app.post("/chat")
async def chat(request: Request):
    form_data = await request.form()
    user_message = form_data.get("message", "").strip()
    
    if user_message:
        with tracer.start_as_current_span("agent_chat_lifecycle") as root_span:
            root_span.set_attribute("chat.user_message", user_message)
            
            context = check_database(user_message)
            enriched_prompt = f"Context: {context}. User says: {user_message}"
            ai_response = call_llm(enriched_prompt)
            
            root_span.set_attribute("chat.agent_response", ai_response)
            chat_history.append({"user": user_message, "ai": ai_response})
            
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# 2. Fetch Telemetry Data
@app.get("/telemetry/data")
async def get_telemetry_data():
    finished_spans = memory_exporter.get_finished_spans()
    
    telemetry_logs = []
    for span in finished_spans:
        duration_ms = (span.end_time - span.start_time) / 1_000_000
        telemetry_logs.append({
            "trace_id": hex(span.context.trace_id),
            "span_id": hex(span.context.span_id),
            "parent_id": hex(span.parent.span_id) if span.parent else "None (Root)",
            "name": span.name,
            "latency_ms": round(duration_ms, 2),
            "attributes": dict(span.attributes)
        })
        
    return telemetry_logs[::-1]


# 3. NEW: Endpoint to clear OpenTelemetry RAM buffer
@app.post("/telemetry/clear")
async def clear_telemetry():
    memory_exporter.clear()
    return {"status": "cleared"}


# 4. Main Split-Screen Dashboard Frontend
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    chat_html = "".join([
        f"<p><b>You:</b> {msg['user']}</p><p style='color: #0066cc;'><b>Agent:</b> {msg['ai']}</p><hr style='border:0; border-top: 1px dashed #eee;'/>" 
        for msg in chat_history
    ])

    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Agent Dashboard</title>
            <style>
                body {{ font-family: system-ui, sans-serif; margin: 0; display: flex; height: 100vh; background-color: #f4f6f9; color: #333; }}
                .section {{ width: 50%; padding: 25px; box-sizing: border-box; display: flex; flex-direction: column; }}
                .left {{ border-right: 1px solid #ddd; background: white; }}
                .right {{ background: #1e1e1e; color: #e0e0e0; }}
                .header-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
                .scrollable {{ flex-grow: 1; overflow-y: auto; border: 1px solid #eee; padding: 15px; border-radius: 6px; background: #fafafa; margin-bottom: 15px; }}
                .telemetry-box {{ flex-grow: 1; overflow-y: auto; font-family: monospace; font-size: 12px; background: #2d2d2d; padding: 15px; border-radius: 6px; color: #a9ff99; white-space: pre-wrap; margin: 0; }}
                .input-group {{ display: flex; gap: 10px; }}
                input[type="text"] {{ flex-grow: 1; padding: 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }}
                
                button {{ padding: 12px 24px; background: #0066cc; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 14px; }}
                button:hover {{ background: #0052a3; }}
                
                .btn-clear {{ background: #444; color: #ff6b6b; padding: 6px 14px; font-size: 12px; border: 1px solid #555; }}
                .btn-clear:hover {{ background: #555; color: #ff8787; }}
                
                h2 {{ margin: 0; font-size: 1.4rem; }}
            </style>
            <script>
                async function fetchTelemetry() {{
                    try {{
                        const response = await fetch('/telemetry/data');
                        const data = await response.json();
                        document.getElementById('telemetry').innerText = JSON.stringify(data, null, 2);
                    }} catch (err) {{
                        console.error("Failed fetching telemetry", err);
                    }}
                }}

                // Triggers backend clear and updates front-end display instantly
                async function clearTelemetry() {{
                    await fetch('/telemetry/clear', {{ method: 'POST' }});
                    document.getElementById('telemetry').innerText = "[]";
                }}

                setInterval(fetchTelemetry, 1500);
                window.onload = fetchTelemetry;
            </script>
        </head>
        <body>
            <div class="section left">
                <div class="header-row">
                    <h2>💬 AI Agent Chat</h2>
                </div>
                <div class="scrollable">
                    {chat_html if chat_html else "<p style='color:#999; text-align:center; margin-top:20px;'>Type a message to see the lifecycle live...</p>"}
                </div>
                <form action="/chat" method="post" class="input-group">
                    <input type="text" name="message" placeholder="Ask something..." required autocomplete="off">
                    <button type="submit">Send</button>
                </form>
            </div>

            <div class="section right">
                <div class="header-row">
                    <h2>📡 Live OpenTelemetry Spans</h2>
                    <button class="btn-clear" onclick="clearTelemetry()">Clear Telemetry Logs</button>
                </div>
                <pre id="telemetry" class="telemetry-box">Waiting for telemetry trace signals...</pre>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)