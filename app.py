"""
Gradio UI for the Weather Agent.
"""

import os
from datetime import datetime

import gradio as gr
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

from agent import create_agent

load_dotenv()

# Create the agent once at module level
agent = create_agent()


def chat_stream(message: str, history: list, session_id: str):
    """Process a chat message and stream the response."""
    config = {"configurable": {"thread_id": session_id}}
    accumulated_content = ""

    for event in agent.stream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode="messages",
    ):
        msg, metadata = event
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, str):
                accumulated_content += msg.content
                yield accumulated_content

    if not accumulated_content:
        yield "I'm sorry, I couldn't process that request."


CUSTOM_CSS = """
/* Viewport meta is set by Gradio, ensure proper scaling */
.gradio-container {
    max-width: 820px !important;
    margin: 0 auto !important;
    padding: 0 1rem !important;
}

/* Header */
#header {
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    padding: 1.25rem 0 0.5rem;
}
#header .header-text {
    text-align: center;
}
#header h1 {
    font-size: 1.35rem;
    font-weight: 700;
    margin: 0;
}
#header p {
    font-size: 0.85rem;
    opacity: 0.6;
    margin: 0.25rem 0 0;
}
#header .logo {
    position: absolute;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 38px;
    height: 38px;
}

/* Chatbot */
#chatbot {
    border-radius: 16px !important;
    height: 480px !important;
}

/* Multimodal input */
#msg-input {
    border-radius: 12px !important;
}
#msg-input textarea {
    font-size: 1rem !important;
}

/* Suggestion chips */
.chip-row {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.25rem 0;
    flex-wrap: wrap;
}
.chip-row button {
    border-radius: 20px !important;
    font-size: 0.82em !important;
    white-space: nowrap !important;
}

/* Hide Gradio footer */
footer {
    display: none !important;
}

/* ---- Mobile (max 640px) ---- */
@media (max-width: 640px) {
    .gradio-container {
        padding: 0 0.5rem !important;
    }

    #header {
        padding: 0.75rem 0 0.25rem;
    }
    #header h1 {
        font-size: 1.15rem;
    }
    #header p {
        font-size: 0.8rem;
    }

    /* Shorter chat area on small screens */
    #chatbot {
        height: 55dvh !important;
        border-radius: 12px !important;
    }

    /* Chips scroll horizontally instead of wrapping */
    .chip-row {
        flex-wrap: nowrap;
        overflow-x: auto;
        justify-content: flex-start;
        gap: 0.4rem;
        padding: 0.25rem 0.25rem;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    .chip-row::-webkit-scrollbar {
        display: none;
    }
    .chip-row button {
        flex-shrink: 0;
        font-size: 0.78em !important;
        padding: 0.35rem 0.75rem !important;
    }
}

/* ---- Tablet (641px – 1024px) ---- */
@media (min-width: 641px) and (max-width: 1024px) {
    .gradio-container {
        max-width: 700px !important;
    }

    #chatbot {
        height: 60dvh !important;
    }
}

/* ---- Large desktop (1025px+) ---- */
@media (min-width: 1025px) {
    #chatbot {
        height: 480px !important;
    }
}
"""


def create_gradio_app():
    """Create and return the Gradio interface."""

    with gr.Blocks(title="Weather Agent") as demo:
        gr.HTML(
            '<div id="header">'
            '<div class="header-text">'
            "<h1>Weather Agent</h1>"
            "<p>Get weather forecasts for any location &mdash; just ask.</p>"
            "</div>"
            '<svg class="logo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
            '<rect width="100" height="100" rx="22" fill="#6366f1"/>'
            '<text x="50" y="64" text-anchor="middle" font-size="42" '
            'font-weight="700" font-family="system-ui,sans-serif" fill="white">W</text>'
            "</svg>"
            "</div>"
        )

        session_id = gr.State(
            value=lambda: f"session_{datetime.now().timestamp()}"
        )

        chatbot = gr.Chatbot(
            elem_id="chatbot",
            show_label=False,
            placeholder=(
                '<div style="display:flex;flex-direction:column;align-items:center;'
                'justify-content:center;height:100%;color:#9ca3af;padding:1.5rem;">'
                '<p style="font-size:1.8rem;margin:0;">&#9925;</p>'
                '<p style="font-size:clamp(0.9rem,2.5vw,1rem);margin:0.5rem 0 0.25rem;'
                'font-weight:500;">How can I help?</p>'
                '<p style="font-size:clamp(0.75rem,2vw,0.85rem);">'
                'Try &ldquo;Weather in Paris next week&rdquo;</p>'
                "</div>"
            ),
        )

        msg = gr.MultimodalTextbox(
            elem_id="msg-input",
            placeholder="Message Weather Agent...",
            show_label=False,
            file_types=["image"],
        )

        # Suggestion chips
        suggestions = [
            "Weather in Paris next week?",
            "Tokyo forecast Jan 20-25",
            "LA weather in fahrenheit",
            "London 5-day forecast",
        ]
        with gr.Row(elem_classes=["chip-row"]):
            for s in suggestions:
                btn = gr.Button(s, variant="secondary", size="sm")
                btn.click(fn=lambda text=s: {"text": text, "files": []}, outputs=[msg])

        gr.Button(
            "New Chat", variant="secondary", size="sm"
        ).click(
            fn=lambda: ([], f"session_{datetime.now().timestamp()}"),
            outputs=[chatbot, session_id],
        )

        # --- Event wiring ---
        def respond(message, chat_history, session):
            text = message.get("text", "").strip()
            files = message.get("files", [])

            if not text and not files:
                yield None, chat_history
                return

            # Display uploaded images in chat
            for f in files:
                chat_history = chat_history + [{"role": "user", "content": f}]

            # Stream agent response for the text portion
            if text:
                chat_history = chat_history + [{"role": "user", "content": text}]
                chat_history = chat_history + [{"role": "assistant", "content": ""}]
                for partial_response in chat_stream(text, chat_history, session):
                    chat_history[-1]["content"] = partial_response
                    yield None, chat_history
            else:
                yield None, chat_history

        msg.submit(respond, [msg, chatbot, session_id], [msg, chatbot])

    return demo


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY environment variable not set!")
        print("Please set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or create a .env file with: OPENAI_API_KEY=your-api-key")
        print()

    demo = create_gradio_app()
    demo.queue()
    demo.launch(share=False, css=CUSTOM_CSS, theme=gr.themes.Soft())
