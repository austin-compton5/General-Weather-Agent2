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


def chat(message: str, history: list, session_id: str) -> str:
    """Process a chat message and return the response."""

    config = {"configurable": {"thread_id": session_id}}

    # Invoke the agent
    result = agent.invoke(
        {"messages": [HumanMessage(content=message)]},
        config=config
    )

    # Get the last AI message
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage):
            return msg.content

    return "I'm sorry, I couldn't process that request."


def create_gradio_app():
    """Create and return the Gradio interface."""

    with gr.Blocks(title="Weather Forecast Agent") as demo:
        gr.Markdown(
            """
            # Weather Forecast Agent

            Chat with this AI assistant to get weather forecasts. The agent will collect:
            - **Location** (latitude & longitude)
            - **Date range** (start and end dates)
            - **Temperature unit** (celsius or fahrenheit)
            - **Timezone**

            Try saying something like: *"I want to know the weather in New York next week"*
            """
        )

        # Session ID for conversation memory
        session_id = gr.State(value=lambda: f"session_{datetime.now().timestamp()}")

        chatbot = gr.Chatbot(
            height=500,
            placeholder="Ask me about the weather forecast for any location!",
        )

        msg = gr.Textbox(
            placeholder="Type your message here...",
            label="Your message",
            lines=2,
        )

        with gr.Row():
            submit_btn = gr.Button("Send", variant="primary")
            clear_btn = gr.Button("Clear Chat")

        gr.Examples(
            examples=[
                "What's the weather going to be like in Paris next week?",
                "I need a forecast for Tokyo from January 20 to January 25",
                "Check the weather for coordinates 51.5074, -0.1278",
                "Weather forecast for Los Angeles in fahrenheit",
            ],
            inputs=msg,
        )

        def respond(message, chat_history, session):
            if not message.strip():
                return "", chat_history

            # Add user message to history
            chat_history = chat_history + [{"role": "user", "content": message}]

            # Get bot response
            bot_response = chat(message, chat_history, session)

            # Add bot response to history
            chat_history = chat_history + [{"role": "assistant", "content": bot_response}]

            return "", chat_history

        def clear_chat():
            new_session = f"session_{datetime.now().timestamp()}"
            return [], new_session

        # Event handlers
        msg.submit(respond, [msg, chatbot, session_id], [msg, chatbot])
        submit_btn.click(respond, [msg, chatbot, session_id], [msg, chatbot])
        clear_btn.click(clear_chat, outputs=[chatbot, session_id])

    return demo


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY environment variable not set!")
        print("Please set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or create a .env file with: OPENAI_API_KEY=your-api-key")
        print()

    demo = create_gradio_app()
    demo.launch(share=False)
