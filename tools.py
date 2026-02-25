"""
Open-Meteo API tool for weather forecasts.
"""

import re
from datetime import date, timedelta

import httpx
from langchain_core.tools import tool


@tool
def geocode_address(address: str) -> str:
    """
    Convert an address, city name, or place to geographic coordinates.
    Always use this tool when the user provides a location as text rather than coordinates.

    Args:
        address: The address or place name to look up (e.g. "Paris, France", "1600 Pennsylvania Ave, Washington DC")

    Returns:
        The resolved location name, latitude, and longitude.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "json", "limit": 1, "q": address},
                headers={"User-Agent": "WeatherAgent/1.0", "Accept-Language": "en"},
            )
            response.raise_for_status()
            data = response.json()

        if not data:
            return f'Could not find a location matching "{address}". Try a different search term.'

        result = data[0]
        lat = float(result["lat"])
        lng = float(result["lon"])
        display_name = result.get("display_name", address)

        return (
            f'Location: "{display_name}"\n'
            f"Latitude: {lat}\n"
            f"Longitude: {lng}"
        )

    except httpx.HTTPStatusError as e:
        return f"Geocoding API error: {e.response.status_code}"
    except Exception as e:
        return f"Geocoding error: {str(e)}"


@tool
def get_weather_forecast(
    latitude: float,
    longitude: float,
    start_date: str | None = None,
    end_date: str | None = None,
    temperature_unit: str = "fahrenheit",
    timezone: str = "auto",
) -> str:
    """
    Fetch weather forecast from Open-Meteo API.

    Args:
        latitude: Latitude of the location (e.g., 40.7128 for New York)
        longitude: Longitude of the location (e.g., -74.0060 for New York)
        start_date: Start date in YYYY-MM-DD format (defaults to today)
        end_date: End date in YYYY-MM-DD format (defaults to 7 days from start)
        temperature_unit: Either 'celsius' or 'fahrenheit' (defaults to 'fahrenheit')
        timezone: Timezone string (defaults to 'auto' which infers from coordinates)

    Returns:
        Weather forecast data as a formatted string
    """
    if start_date is None:
        start_date = date.today().isoformat()
    if end_date is None:
        end_date = (date.today() + timedelta(days=7)).isoformat()
    base_url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "temperature_unit": temperature_unit,
        "timezone": timezone,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "windspeed_10m_max",
            "weathercode"
        ],
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

        # Format the response nicely
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        precip_prob = daily.get("precipitation_probability_max", [])
        wind = daily.get("windspeed_10m_max", [])
        weather_codes = daily.get("weathercode", [])

        # Weather code mapping
        weather_descriptions = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Foggy",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail",
        }

        unit_symbol = "°F" if temperature_unit == "fahrenheit" else "°C"

        result_lines = [
            f"Weather Forecast for ({latitude}, {longitude})",
            f"Timezone: {timezone}",
            "-" * 50,
        ]

        for i, date in enumerate(dates):
            weather_desc = weather_descriptions.get(weather_codes[i], "Unknown")
            result_lines.append(
                f"\n{date}:\n"
                f"  Condition: {weather_desc}\n"
                f"  Temperature: {temp_min[i]}{unit_symbol} - {temp_max[i]}{unit_symbol}\n"
                f"  Precipitation: {precip[i]}mm (probability: {precip_prob[i]}%)\n"
                f"  Max Wind: {wind[i]} km/h"
            )

        return "\n".join(result_lines)

    except httpx.HTTPStatusError as e:
        return f"API Error: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Error fetching weather data: {str(e)}"


# List of all tools for easy import
tools = [geocode_address, get_weather_forecast]
