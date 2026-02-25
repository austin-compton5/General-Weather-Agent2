"""
LangGraph Weather Agent with Gemini.
"""

from datetime import datetime
from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from tools import tools


# ============================================================================
# State Definition
# ============================================================================

class WeatherState(TypedDict):
    """State for the weather agent conversation."""
    messages: Annotated[list, add_messages]


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """You are a helpful weather assistant. Your job is to collect the necessary information from the user to fetch a weather forecast.

You need to collect these 6 pieces of information:
1. **Latitude** - The latitude of the location (a number between -90 and 90)
2. **Longitude** - The longitude of the location (a number between -180 and 180)
3. **Start date** - The start date for the forecast (YYYY-MM-DD format)
4. **End date** - The end date for the forecast (YYYY-MM-DD format)
5. **Temperature unit** - Either 'celsius' or 'fahrenheit'
6. **Timezone** - A timezone string like 'America/New_York', 'Europe/London', 'Asia/Tokyo', or 'auto'

Guidelines:
- If the message starts with [My current location: latitude X, longitude Y], extract and use those coordinates directly — do not ask the user for their location
- If the user provides a city name instead of coordinates, use the geocode_address tool to resolve it to coordinates
- If dates are missing, ask for them. The forecast can be up to 16 days in the future
- If temperature unit is not specified, ask their preference
- If timezone is not specified, suggest 'auto' or ask for their timezone
- Once you have ALL 6 pieces of information, call the get_weather_forecast tool
- After getting the weather data, present it to the user in a friendly, readable format
- Today's date is {today}

Be conversational and helpful. Ask clarifying questions one or two at a time rather than overwhelming the user with all questions at once."""


# ============================================================================
# Agent Factory
# ============================================================================

def create_agent():
    """Create and return the compiled LangGraph agent."""

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.7,
    )

    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: WeatherState):
        """Main agent node that processes messages."""
        system_message = SystemMessage(
            content=SYSTEM_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"))
        )
        messages = [system_message] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: WeatherState):
        """Determine if we should continue to tools or end."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END

    # Build the graph
    workflow = StateGraph(WeatherState)

    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))

    # Add edges
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")

    # Compile with memory
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
