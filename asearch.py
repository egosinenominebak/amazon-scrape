import re
import time
from concurrent.futures import ThreadPoolExecutor
import random

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from bs4 import BeautifulSoup
from requests import HTTPError
from fake_useragent import UserAgent

MAX_PAGES = 50
RETRY_COUNT = 3  # Number of retries for failed requests

# Initialize UserAgent rotator
ua = UserAgent()

def __response_hook(r, *args, **kwargs):
    try:
        # Only raise HTTPError for client or server errors (4xx or 5xx)
        r.raise_for_status()
    except HTTPError as e:
        if e.response.status_code >= 400:  # Only handle 4xx and 5xx errors
            raise HTTPError(
                BeautifulSoup(r.text, "html.parser").text.strip(), request=e.request, response=e.response
            ) from e

session = requests.Session()

def get(url, **kwargs):
    # Rotate user agent
    session.headers.update({"User-Agent": ua.random})
    for attempt in range(RETRY_COUNT):  # Retry mechanism
        try:
            response = session.get(url, allow_redirects=True, **kwargs) # Explicit redirect handling
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt < RETRY_COUNT - 1:
                wait_time = random.uniform(1, 3)  # Random delay between 1 and 3 seconds
                time.sleep(wait_time)
                print(f"Retrying request to {url} (Attempt {attempt + 2}/{RETRY_COUNT})")
            else:
                print(f"Failed to fetch {url} after {RETRY_COUNT} attempts: {e}")
                raise  # Reraise the exception after all retries fail

@st.cache_data
def search(q: str):
    site = "amazon.it"
    url = f"https://{site}/s?k={q}"

    soup = BeautifulSoup(get(url).content, "html.parser")
    pages_elements = soup.find_all("span", "s-pagination-item")
    pages = int(pages_elements[-1].text) if pages_elements else 1  # Handle cases where there's only one page

    if pages > MAX_PAGES:
        pages = MAX_PAGES

    def get_results(page: int):
        soup = BeautifulSoup(get(url, params={"page": page}).content, "html.parser")
        divs = soup.find_all("div", attrs={"data-component-type": "s-search-result"})

        if not divs:
            print(f"No results found on page {page}.")
            return []

        results = []
        for div in divs:
            try:
                # Initialize result dict with all expected keys
                result = {
                    "asin": None,
                    "img": None,
                    "description": None,
                    "link": None,
                    "price": None,
                    "rating": None,
                    "number_of_reviews": None,
                }

                asin = div.get("data-asin")
                result["asin"] = asin
                img_tag = div.find("img", "s-image")
                if img_tag:
                    result["img"] = img_tag.get("src")
                h2_tags = div.find_all("h2")
                if h2_tags:
                    result["description"] = ": ".join(
                        h2.text.strip() for h2 in h2_tags
                    )
                result["link"] = f"https://{site}/dp/{asin}" if asin else None

                price = div.find("span", "a-price")
                if price:
                    price_value = price.find("span", "a-offscreen")
                    if price_value:
                        result["price"] = price_value.text

                rating = div.find(
                    "span",
                    attrs={
                        "aria-label": lambda l: l
                        and re.fullmatch(".* su .* stelle", l)
                    },
                )
                if rating:
                    rating_value = rating.get("aria-label").split(" ")[0].replace(",", ".")
                    result["rating"] = float(rating_value)

                number_of_reviews = div.find(
                    "a", href=lambda h: h and "#customerReviews" in h
                )
                if number_of_reviews:
                    reviews_text = number_of_reviews.text.strip()
                    reviews_number = re.sub("[^0-9]", "", reviews_text)
                    if reviews_number:
                        result["number_of_reviews"] = int(reviews_number)

                results.append(result)
            except Exception as e:
                print(f"Error processing item: {e}")
        return results

    with ThreadPoolExecutor() as t:
        all_results = [
            item for sublist in t.map(get_results, range(1, pages + 1)) for item in sublist
        ]
    return all_results

st.title("ASearch")
st.subheader("Una ricerca migliore su Amazon")

term = st.text_input("Cerca")

if term:
    df = pd.DataFrame(search(term))

    if not df.empty:
        # Clean and convert the price column
        if 'price' in df.columns:
            df["price_value"] = (
                df.price.str.replace("€", "")
                .str.replace(".", "")
                .str.replace(",", ".")
                .astype(float, errors='ignore')
            )
        else:
            df["price_value"] = None  # Assign None if 'price' column is missing

        # Determine price range for the slider
        if df["price_value"].notnull().any():
            price_min = float(df["price_value"].min())
            price_max = float(df["price_value"].max())
        else:
            price_min = 0.0
            price_max = 0.0

        price_range = st.slider(
            "Prezzo",
            price_min,
            price_max,
            (price_min, price_max),
            format="€%.2f",
        )

        # Filter DataFrame based on price range
        df_filtered = df[df["price_value"].between(*price_range)]

        # Define the columns you want to display
        columns_to_display = [
            "link",
            "img",
            "description",
            "price_value",
            "number_of_reviews",
            "rating",
        ]

        # Check which columns exist in your DataFrame
        existing_columns = [col for col in columns_to_display if col in df_filtered.columns]

        # Adjust the column configurations
        column_configurations = {
            "link": st.column_config.LinkColumn("Link", display_text="Apri"),
            "img": st.column_config.ImageColumn("Immagine"),
            "description": "Descrizione",
            "price_value": st.column_config.NumberColumn("Prezzo", format="€%.2f"),
            "number_of_reviews": "Recensioni",
            "rating": st.column_config.NumberColumn("Valutazione", format="%.1f ⭐️"),
        }

        # Filter column configurations for existing columns
        existing_column_configurations = {
            col: config for col, config in column_configurations.items() if col in existing_columns
        }

        st.dataframe(
            df_filtered[existing_columns],
            column_config=existing_column_configurations,
            use_container_width=True,
        )

        # Plot the histogram if price data is available
        if 'price_value' in df_filtered.columns and df_filtered['price_value'].notnull().any():
            st.plotly_chart(px.histogram(df_filtered, x="price_value"))
        else:
            st.write("No price data available to plot.")
    else:
        st.write("No results found for your search.")
