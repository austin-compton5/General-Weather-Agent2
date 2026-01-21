# Weather Forecast Agent

A minimal LangGraph agent that fetches weather forecasts through natural conversation.

## Overview

This project demonstrates a simple agentic workflow using:
- **LangGraph** - Orchestrates the conversation flow and tool calling
- **Google Gemini** (gemini-1.5-flash) - Powers the conversational AI
- **Open-Meteo API** - Provides free weather forecast data
- **Gradio** - Web UI for chatting with the agent

The agent collects the following through conversation, then fetches and presents a weather forecast:

- **Location** - City name or coordinates (the agent converts city names to lat/long)
- **Date range** - When you want the forecast for
- **Temperature unit** - Celsius or Fahrenheit
- **Timezone** - Optional, defaults to auto

## Setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Add your Google API key to `.env`:
   ```
   GOOGLE_API_KEY=your-api-key-here
   ```
   Get a key at: https://aistudio.google.com/apikey

## Usage

```bash
source venv/bin/activate
python app.py
```

Open the Gradio URL in your browser and start chatting. Try:
- "What's the weather in Paris next week?"
- "I need a forecast for Tokyo from January 20 to January 25"
- "Weather for Los Angeles in fahrenheit"

## Project Structure

```
├── agent.py      # LangGraph agent definition
├── tools.py      # Open-Meteo weather API tool
├── app.py        # Gradio web interface
├── .env          # API key configuration
└── requirements.txt
```

## How It Works

1. User sends a message through the Gradio chat interface
2. The agent (Gemini) processes the message and determines what information is still needed
3. Once all required info is collected (lat/long, dates, unit, timezone), the agent calls the weather tool
4. The tool fetches data from Open-Meteo and returns formatted results
5. The agent presents the forecast to the user
